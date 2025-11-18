import asyncio
import gspread
from google.oauth2.service_account import Credentials
from zoneinfo import ZoneInfo
from eangenerator import genera_ean13
from dotenv import load_dotenv
import os

import asyncpg
from quart import Quart, jsonify, request, abort, websocket
from quart_cors import cors

app = Quart(__name__)

app = cors(app, allow_origin="http://localhost:3000")

load_dotenv()

DB_CONFIG = {
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "database": os.getenv("DB_NAME"),
    "host": os.getenv("DB_HOST"),
    "port": os.getenv("DB_PORT"),
}

pool: asyncpg.Pool | None = None

notification_queue: asyncio.Queue[dict] = asyncio.Queue()
connected_websockets: set = set()

listener_task: asyncio.Task | None = None
dispatcher_task: asyncio.Task | None = None


# SCOPES necessari per modificare Google Sheets
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# ID del tuo spreadsheet (lo trovi nell'URL di Google Sheets)
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")  # es: "1AbCdEfGhIjKlMnOpQr..."

# Nome del worksheet (la tab) da aggiornare
WORKSHEET_NAME = os.getenv("WORKSHEET_NAME")

_credentials = None
_client = None
_worksheet = None

def get_worksheet():
    global _credentials, _client, _worksheet

    if _worksheet is None:
        if _credentials is None:
            _credentials = Credentials.from_service_account_file(
                os.getenv("SERVICE_ACCOUNT_FILE_NAME"),
                scopes=SCOPES,
            )
        if _client is None:
            _client = gspread.authorize(_credentials)

        _worksheet = _client.open_by_key(SPREADSHEET_ID).worksheet(WORKSHEET_NAME)

    return _worksheet



LAST_INBOUND_SQL = """
                   SELECT u.barcode,
                          u.nome,
                          u.cognome,
                          l.event_time
                   FROM (SELECT DISTINCT
                         ON (barcode)
                             id,
                             barcode,
                             event_time,
                             direction
                         FROM log
                         ORDER BY barcode, event_time DESC) AS l
                            JOIN users u
                                 ON u.barcode = l.barcode
                   WHERE l.direction = 'CHECKIN'
                   ORDER BY l.event_time DESC; \
                   """



async def fetch_last_inbound_rows():
    """
    Esegue la query LAST_INBOUND_SQL e restituisce
    una lista di liste pronte per lo Sheet.
    Ogni riga: [barcode, nome, cognome, event_time_iso]
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(LAST_INBOUND_SQL)

    result = []
    for r in rows:
        event_time = r["event_time"]
        event_time_str = format_event_time_ita(event_time)

        result.append([
            r["barcode"],
            r["nome"],
            r["cognome"],
            event_time_str,
        ])

    return result



def write_full_table_to_sheet(rows_for_sheet):
    """
    rows_for_sheet: lista di liste [barcode, nome, cognome, event_time_iso]
    Scrive tutto sullo Sheet a partire da A2 (colonne A-D).
    """
    ws = get_worksheet()

    # Pulisce le righe esistenti (A2:D)
    ws.batch_clear(["A2:D"])

    if not rows_for_sheet:
        return

    # Scrive i nuovi dati (A2 come top-left)
    ws.update("A2", rows_for_sheet)



async def refresh_sheet_from_db():
    """
    Legge i dati dal DB e aggiorna il Google Sheet.
    """
    # 1) Prendo i dati dal DB
    rows_for_sheet = await fetch_last_inbound_rows()

    # 2) Scrivo sullo Sheet in un thread separato
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(
        None,
        write_full_table_to_sheet,
        rows_for_sheet,
    )


async def listen_to_log_notifications():
    """
    Mantiene una connessione dedicata per LISTEN log_changes
    e mette le notifiche in una coda asyncio.
    """
    conn = await asyncpg.connect(**DB_CONFIG)

    def _listener(connection, pid, channel, payload):
        # metto nella coda un evento generico
        notification_queue.put_nowait({
            "channel": channel,
            "payload": payload,
        })

    await conn.add_listener("log_changes", _listener)

    try:
        # tieni viva la connessione, asyncpg gestisce le notify tramite il listener
        while True:
            await asyncio.sleep(3600)
    finally:
        await conn.close()



async def notification_dispatcher():
    loop = asyncio.get_running_loop()

    while True:
        event = await notification_queue.get()

        message = {
            "type": "logs_changed",
            "channel": event["channel"],
            "payload": event["payload"],
        }

        # Broadcast ai websocket
        dead = []
        for ws in list(connected_websockets):
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)

        for ws in dead:
            connected_websockets.discard(ws)

        # Qui non ci interessa il contenuto di `event`, ci basta il trigger:
        # quando arriva una notify, ricalcoliamo tutta la tabella e la mandiamo allo Sheet
        asyncio.create_task(refresh_sheet_from_db())



@app.before_serving
async def startup():
    global pool, listener_task, dispatcher_task

    pool = await asyncpg.create_pool(**DB_CONFIG)

    # task che ascolta LISTEN/NOTIFY
    listener_task = asyncio.create_task(listen_to_log_notifications())
    # task che prende dalla coda e manda sui websocket
    dispatcher_task = asyncio.create_task(notification_dispatcher())


@app.after_serving
async def shutdown():
    global pool, listener_task, dispatcher_task

    if listener_task:
        listener_task.cancel()
    if dispatcher_task:
        dispatcher_task.cancel()

    if pool:
        await pool.close()



@app.before_serving
async def create_db_pool():
    global pool
    pool = await asyncpg.create_pool(**DB_CONFIG)


@app.after_serving
async def close_db_pool():
    global pool
    if pool:
        await pool.close()


# ==========================
#         USERS
# ==========================

# GET /users -> getAll
@app.get("/users")
async def get_all_users():
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT barcode, nome, cognome FROM users ORDER BY cognome, nome"
        )
    users = [dict(r) for r in rows]
    return jsonify(users)


# GET /users/<barcode> -> get by PK
@app.get("/users/<string:barcode>")
async def get_user(barcode: str):
    if len(barcode) != 13 or not barcode.isdigit():
        abort(400, "Barcode non valido (deve essere 13 cifre)")

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT barcode, nome, cognome FROM users WHERE barcode = $1",
            barcode,
        )
    if not row:
        abort(404, "Utente non trovato")
    return jsonify(dict(row))


# POST /users -> insert
# Body JSON: { "barcode": "1234567890123", "nome": "...", "cognome": "..." }
@app.post("/users")
async def create_user():
    data = await request.get_json(force=True)

    barcode = data.get("barcode")
    nome = data.get("nome")
    cognome = data.get("cognome")

    if not barcode or len(barcode) != 13 or not barcode.isdigit():
        abort(400, "Barcode obbligatorio, 13 cifre numeriche")
    if not nome or not cognome:
        abort(400, "Nome e cognome sono obbligatori")

    async with pool.acquire() as conn:
        try:
            await conn.execute(
                """
                INSERT INTO users (barcode, nome, cognome)
                VALUES ($1, $2, $3)
                """,
                barcode,
                nome,
                cognome,
            )
        except asyncpg.UniqueViolationError:
            abort(409, "Utente con questo barcode già esistente")

    return jsonify({"message": "Utente creato"}), 201


# DELETE /users/<barcode>
@app.delete("/users/<string:barcode>")
async def delete_user(barcode: str):
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM log WHERE barcode = $1",
            barcode,
        )
        result = await conn.execute(
            "DELETE FROM users WHERE barcode = $1",
            barcode,
        )
    # result es. "DELETE 1"
    deleted_rows = int(result.split()[-1])
    if deleted_rows == 0:
        abort(404, "Utente non trovato")
    return jsonify({"message": "Utente cancellato"})


# ==========================
#          LOGS
# ==========================

# GET /logs -> getAll, con filtri opzionali
# /logs?barcode=...&from=2025-01-01&to=2025-01-31
@app.get("/logs")
async def get_all_logs():
    barcode = request.args.get("barcode")
    from_date = request.args.get("from")
    to_date = request.args.get("to")

    query = """
        SELECT id, barcode, event_time, direction
        FROM log
        WHERE 1=1
    """
    params = []
    idx = 1

    if barcode:
        query += f" AND barcode = ${idx}"
        params.append(barcode)
        idx += 1

    if from_date:
        query += f" AND event_time >= ${idx}"
        params.append(from_date)
        idx += 1

    if to_date:
        query += f" AND event_time <= ${idx}"
        params.append(to_date)
        idx += 1

    query += " ORDER BY event_time DESC"

    async with pool.acquire() as conn:
        rows = await conn.fetch(query, *params)

    logs = []
    for r in rows:
        item = dict(r)
        # event_time non è JSON serializable di default, lo trasformo in stringa ISO
        item["event_time"] = item["event_time"].isoformat()
        logs.append(item)

    return jsonify(logs)


# GET /logs/<id>
@app.get("/logs/<int:log_id>")
async def get_log(log_id: int):
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, barcode, event_time, direction FROM log WHERE id = $1",
            log_id,
        )
    if not row:
        abort(404, "Log non trovato")

    item = dict(row)
    item["event_time"] = item["event_time"].isoformat()
    return jsonify(item)

# GET /logs/<id>
@app.get("/users/newean")
async def get_new_ean():
    new_ean = genera_ean13()
    found = True
    count = 0
    while found and count < 10:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT barcode FROM users WHERE barcode = $1",
                new_ean,
            )
        if not row:
            found = False
        else:
            new_ean = genera_ean13()
        count+=1


    if count >= 10:
        abort(500, "Non e' stato possibile trovare un ean libero")

    item = dict({"new_ean": new_ean})
    return jsonify(item)


# POST /logs -> insert
# Body JSON: { "barcode": "1234567890123", "direction": "CHECKIN"/"CHECKOUT", "event_time": opzionale }
@app.post("/logs")
async def create_log():
    data = await request.get_json(force=True)

    barcode = data.get("barcode")
    direction = data.get("direction")
    event_time = data.get("event_time")  # opzionale

    if not barcode:
        abort(400, "Barcode obbligatorio")
    if direction not in ("CHECKIN", "CHECKOUT"):
        abort(400, "direction deve essere CHECKIN o CHECKOUT")

    async with pool.acquire() as conn:
        # opzionalmente controlliamo che l'utente esista
        user_exists = await conn.fetchval(
            "SELECT 1 FROM users WHERE barcode = $1",
            barcode,
        )
        if not user_exists:
            abort(400, "Utente non esiste per questo barcode")

        if event_time:
            query = """
                INSERT INTO log (barcode, direction, event_time)
                VALUES ($1, $2, $3)
                RETURNING id
            """
            log_id = await conn.fetchval(query, barcode, direction, event_time)
        else:
            query = """
                INSERT INTO log (barcode, direction)
                VALUES ($1, $2)
                RETURNING id
            """
            log_id = await conn.fetchval(query, barcode, direction)

    return jsonify({"message": "Log creato", "id": log_id}), 201


# DELETE /logs/<id>
@app.delete("/logs/<int:log_id>")
async def delete_log(log_id: int):
    async with pool.acquire() as conn:
        result = await conn.execute("DELETE FROM log WHERE id = $1", log_id)
    deleted_rows = int(result.split()[-1])
    if deleted_rows == 0:
        abort(404, "Log non trovato")
    return jsonify({"message": "Log cancellato"})

@app.websocket("/ws/logs")
async def logs_websocket():
    # ottieni l'oggetto websocket reale
    ws = websocket._get_current_object()
    connected_websockets.add(ws)

    try:
        # opzionale: il client può mandare messaggi, ma qui ci basta tenerlo aperto
        while True:
            # ci mettiamo solo in attesa che il client chiuda
            # se non vuoi leggere niente, puoi fare un piccolo sleep
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        pass
    except Exception:
        pass
    finally:
        connected_websockets.discard(ws)

def format_event_time_ita(event_time):
    """
    Converte l'event_time nel fuso Europe/Rome e lo formatta come:
    HH:MM DD/MM/YYYY
    """
    if event_time is None:
        return ""

    # Se è naive (senza tzinfo), assumiamo che sia in UTC
    if event_time.tzinfo is None:
        event_time = event_time.replace(tzinfo=ZoneInfo("UTC"))

    # Converte nel fuso di Roma
    event_time_it = event_time.astimezone(ZoneInfo("Europe/Rome"))

    # Formato richiesto: HH:MM DD/MM/YYYY
    return event_time_it.strftime("%H:%M %d/%m/%Y")


# ==========================
#       AVVIO SERVER
# ==========================

if __name__ == "__main__":
    # quart run -h 0.0.0.0 -p 5000
    app.run()

