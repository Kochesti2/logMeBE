# logMeBE

Backend HTTP + WebSocket del sistema **logme** (registro presenze tramite barcode EAN-13).
Scritto in Python con [Quart](https://quart.palletsprojects.com/) (versione async di Flask) e PostgreSQL via `asyncpg`.

> Repository: `git@github.com:Kochesti2/logMeBE.git`

---

## 1. Panoramica

logMeBE espone una API REST per gestire **utenti** (identificati da un barcode EAN-13), **log di accesso** (`CHECKIN` / `CHECKOUT`) e **manager** (gli operatori che si autenticano al frontend con JWT). Inoltre:

- ascolta le notifiche PostgreSQL `LISTEN log_changes` (emesse da un trigger sulla tabella `log`) e le inoltra ai client collegati al WebSocket `/ws/logs`;
- a ogni modifica della tabella `log` riscrive un **Google Sheet** con l'elenco delle persone attualmente "dentro" (ultimo evento = `CHECKIN`);
- può inviare via **email (SMTP)** l'immagine PNG del barcode a un utente.

### Il sistema logme

| Modulo | Tecnologia | Ruolo |
|---|---|---|
| `clogger` | C++ (libpq) | Legge i barcode da un lettore (stdin), scrive direttamente nella tabella `log` del DB. Il programma `cleanup_table`, lanciato da cron alle 23:59, svuota la tabella `log`. |
| `logMeBE` (questo) | Python / Quart | API REST + WebSocket, autenticazione manager, sync Google Sheet, email. |
| `log-me-app` | Next.js | Frontend web; chiama l'API (`NEXT_PUBLIC_API_BASE_URL`) e il WebSocket (`NEXT_PUBLIC_WS_URL`). |

```
  [lettore barcode]
         |  stdin
         v
     clogger  ---------- INSERT INTO log ---------+
                                                   |
                                                   v
  log-me-app  --HTTP (JWT)-->  logMeBE  <--->  PostgreSQL
  (browser)   <--WS /ws/logs--    |       ^   (users, log, managers,
                                  |       |    trigger -> NOTIFY log_changes)
                                  |       +-- LISTEN log_changes
                                  +--> Google Sheets (service account)
                                  +--> Server SMTP (email barcode)
```

Nota: `clogger` **non** passa dal backend: scrive sul DB, il trigger emette `NOTIFY`, e il backend notifica frontend e Google Sheet.

### Endpoint

| Metodo | Path | Auth | Descrizione |
|---|---|---|---|
| POST | `/auth/register` | no | Registra un manager (creato **non attivo**, massimo 10 manager) |
| POST | `/auth/login` | no | Restituisce `{access_token, token_type}` (JWT HS256, validità 24h) |
| GET | `/users` | no | Elenco utenti (barcode, nome, cognome, email) |
| GET | `/users/<barcode>` | no | Dettaglio utente |
| GET | `/users/newean` | no | Genera un EAN-13 non ancora usato |
| POST | `/users` | Bearer | Crea utente `{barcode, nome, cognome, email}` |
| POST | `/users/send_barcode` | Bearer | Invia via email il barcode `{barcode, email}` |
| DELETE | `/users/<barcode>` | Bearer | Elimina utente e i suoi log |
| GET | `/logs?barcode=&from=&to=` | no | Elenco log (date in formato ISO) |
| GET | `/logs/<id>` | no | Dettaglio log |
| POST | `/logs` | Bearer | Crea log `{barcode, direction, event_time?}` |
| DELETE | `/logs/<id>` | Bearer | Elimina log |
| WS | `/ws/logs` | no | Riceve `{"type":"logs_changed",...}` a ogni modifica di `log` |

---

## 2. Stack e prerequisiti

- **Python**: la CI (`.github/workflows/ci.yml`) usa **Python 3.14**. Il codice richiede almeno 3.10 (sintassi `X | None`, `zoneinfo`). Compatibilità con versioni diverse da 3.14: *da verificare*.
- **PostgreSQL**: la CI usa `postgres:15`. Servono PL/pgSQL (incluso di default) e `LISTEN/NOTIFY`.
- **Dipendenze Python principali** (`requirements.txt`, versioni bloccate): Quart 0.20.0, quart-cors 0.8.0, Hypercorn 0.18.0, asyncpg 0.30.0, PyJWT 2.8.0, passlib 1.7.4 + bcrypt 4.1.2, python-dotenv 1.2.1, gspread 6.2.1, google-auth 2.41.1, python-barcode 0.16.1, pillow 12.0.0.
- **Pacchetti di sistema** (Debian/Ubuntu):
  ```bash
  sudo apt update
  sudo apt install -y git python3 python3-venv python3-pip tzdata postgresql-client
  # solo se pip deve compilare qualche pacchetto (es. asyncpg senza wheel per la tua versione di Python):
  sudo apt install -y build-essential python3-dev
  ```
  `tzdata` serve per `ZoneInfo("Europe/Rome")` usato nel Google Sheet.
- **Servizi esterni opzionali**: account di servizio Google (Sheets API), server SMTP con STARTTLS.

---

## 3. Struttura del progetto

```
app.py                     # app Quart: endpoint users/logs, WebSocket, LISTEN/NOTIFY, Google Sheet, email
auth.py                    # blueprint /auth (register/login), JWT, decorator @auth_required
eangenerator.py            # generazione EAN-13 casuale con checksum
migrations/
  001_a_initial.sql        # tabelle users, log, enum access_direction, trigger NOTIFY
  001_create_managers_table.sql  # tabella managers
conftest.py, pytest.ini    # configurazione test (pytest-asyncio)
tests/                     # test end-to-end delle API (vedi tests/README.md)
requirements.txt           # dipendenze runtime
requirements-test.txt      # dipendenze di test
.github/workflows/ci.yml   # CI GitHub Actions con Postgres 15
```

File attesi ma **non versionati** (vedi `.gitignore`): `.env`, `.env.test`, `service_account.json`, `venv/` / `.venv/`.

---

## 4. Installazione su server Linux

Esempio con utente di sistema `logme` e cartella `/opt/logme/logMeBE` (percorsi a scelta).

### 4.1 Utente e codice

```bash
sudo useradd --system --create-home --home-dir /opt/logme --shell /usr/sbin/nologin logme
sudo -u logme git clone git@github.com:Kochesti2/logMeBE.git /opt/logme/logMeBE
# (se il server non ha una chiave SSH su GitHub usa l'URL https://github.com/Kochesti2/logMeBE.git)
```

### 4.2 Ambiente virtuale e dipendenze

```bash
# percorsi assoluti: la home /opt/logme creata da useradd può avere permessi 700/750,
# quindi un "cd" eseguito dal tuo utente amministratore fallirebbe
sudo -u logme -H python3 -m venv /opt/logme/logMeBE/venv
sudo -u logme -H /opt/logme/logMeBE/venv/bin/pip install --upgrade pip
sudo -u logme -H /opt/logme/logMeBE/venv/bin/pip install -r /opt/logme/logMeBE/requirements.txt
```

Non c'è uno step di build.

### 4.3 Database

Crea DB, utente e schema come descritto nella [sezione 6](#6-database).

### 4.4 Configurazione

```bash
sudo -u logme cp /dev/null /opt/logme/logMeBE/.env
sudo -u logme nano /opt/logme/logMeBE/.env      # contenuto: vedi sezione 5
sudo chmod 600 /opt/logme/logMeBE/.env
# se usi Google Sheets, copia il JSON del service account:
sudo install -o logme -g logme -m 600 service_account.json /opt/logme/logMeBE/service_account.json
```

### 4.5 Avvio manuale (prova)

`python app.py` usa il server di sviluppo di Quart (`app.run()`, default `127.0.0.1:5000`). In produzione usa **Hypercorn** (già in `requirements.txt`, supporta WebSocket):

```bash
# va lanciato dalla cartella del progetto: lì vengono cercati il modulo app e il file .env
sudo -u logme -H bash -c 'cd /opt/logme/logMeBE && ./venv/bin/hypercorn app:app --bind 127.0.0.1:5000'
```

Usa **un solo worker** (default di Hypercorn): la lista dei WebSocket connessi e il listener `LISTEN` sono in memoria nel processo; con più worker ognuno aggiornerebbe il Google Sheet.

La porta 5000 è quella attesa dal frontend come default (`ws://localhost:5000/ws/logs` in `log-me-app/src/app/logs/page.tsx`).

### 4.6 Avvio come servizio systemd

`/etc/systemd/system/logmebe.service`:

```ini
[Unit]
Description=logMeBE (API logme)
After=network-online.target postgresql.service
Wants=network-online.target

[Service]
Type=simple
User=logme
Group=logme
WorkingDirectory=/opt/logme/logMeBE
# Le variabili vengono lette da .env tramite python-dotenv (load_dotenv in app.py/auth.py).
# In alternativa: EnvironmentFile=/opt/logme/logMeBE/.env (formato KEY=valore, senza "export").
ExecStart=/opt/logme/logMeBE/venv/bin/hypercorn app:app --bind 127.0.0.1:5000 --access-logfile - --error-logfile -
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now logmebe
sudo systemctl status logmebe
```

`WorkingDirectory` è importante: `SERVICE_ACCOUNT_FILE_NAME` è un path relativo alla directory corrente se non lo indichi assoluto.

### 4.7 Reverse proxy (nginx) con HTTPS

Consigliato per esporre l'API al browser. Il WebSocket richiede gli header `Upgrade`/`Connection`.

```nginx
server {
    listen 443 ssl;
    server_name api.example.com;               # da adattare

    ssl_certificate     /etc/letsencrypt/live/api.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/api.example.com/privkey.pem;

    location /ws/ {
        proxy_pass http://127.0.0.1:5000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_read_timeout 3600s;
    }

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Con HTTPS il frontend deve usare `https://` per l'API e `wss://` per il WebSocket. Ricorda di aggiornare il CORS (sezione 7).

---

## 5. Variabili d'ambiente

Caricate da un file `.env` con `load_dotenv()` (`app.py`, `auth.py`); le variabili già presenti nell'ambiente **non** vengono sovrascritte dal `.env`.

| Nome | Obbl. | Default | Descrizione | Esempio |
|---|---|---|---|---|
| `DB_HOST` | sì | nessuno (asyncpg ricade su `PGHOST` o sul socket Unix locale) | Host PostgreSQL | `localhost` |
| `DB_PORT` | no | nessuno (asyncpg ricade su `PGPORT` o 5432) | Porta PostgreSQL | `5432` |
| `DB_NAME` | sì | nessuno | Nome database | `logme` |
| `DB_USER` | sì | nessuno | Utente DB | `logme` |
| `DB_PASSWORD` | sì | nessuno | Password DB | `CambiaMi!` |
| `SECRET_KEY` | sì (in prod.) | `dev_secret_key_change_me` | Chiave di firma dei JWT (HS256). **Cambiala**: col default chiunque può generare token validi | stringa casuale lunga |
| `SPREADSHEET_ID` | per Google Sheet | nessuno | ID del foglio (dall'URL di Google Sheets) | `1AbCdEf...` |
| `WORKSHEET_NAME` | per Google Sheet | nessuno | Nome della tab da aggiornare (scrive in `A2:D`) | `Presenti` |
| `SERVICE_ACCOUNT_FILE_NAME` | per Google Sheet | nessuno | Path del JSON del service account Google | `service_account.json` |
| `EMAIL_SMTP_SERVER` | per email | nessuno | Server SMTP (usa STARTTLS) | `smtp.gmail.com` |
| `EMAIL_SMTP_PORT` | per email | nessuno | Porta SMTP (convertita in `int`) | `587` |
| `EMAIL_USERNAME` | per email | nessuno | Login SMTP e mittente (`From`) | `presenze@example.com` |
| `EMAIL_PASSWORD` | per email | nessuno | Password SMTP (o app password) | `xxxx` |
| `EMAIL_OGGETTO` | per email | nessuno | Oggetto dell'email | `Il tuo barcode` |
| `WORKING_PLACE_NAME` | per email | nessuno | Firma nel corpo email ("Team ..."); se manca, l'invio va in errore 500 | `Palestra XYZ` |
| `SEND_EMAIL_ON_USER_REGISTER` | no | non impostata = disattivo | Se **valorizzata con qualsiasi stringa non vuota** (anche `false` o `0`!) invia il barcode via email alla creazione dell'utente. Per disattivare, **non definirla** | `1` |

Note:
- Durata del token (24h) e algoritmo (HS256) sono costanti in `auth.py`, non configurabili via env.
- Le origini CORS sono **hardcoded** in `app.py` (vedi sezione 7).
- Il file `.env.test` è usato solo dai test (`conftest.py`).

### Esempio `.env`

```dotenv
# Database
DB_HOST=localhost
DB_PORT=5432
DB_NAME=logme
DB_USER=logme
DB_PASSWORD=CambiaMi!

# JWT - genera con: python3 -c "import secrets; print(secrets.token_urlsafe(64))"
SECRET_KEY=incolla-qui-una-stringa-casuale

# Google Sheets (opzionale)
SPREADSHEET_ID=1AbCdEfGhIjKlMnOpQr
WORKSHEET_NAME=Presenti
SERVICE_ACCOUNT_FILE_NAME=/opt/logme/logMeBE/service_account.json

# Email (opzionale)
EMAIL_SMTP_SERVER=smtp.example.com
EMAIL_SMTP_PORT=587
EMAIL_USERNAME=presenze@example.com
EMAIL_PASSWORD=password-smtp
EMAIL_OGGETTO=Il tuo barcode logme
WORKING_PLACE_NAME=Nome Sede
# SEND_EMAIL_ON_USER_REGISTER=1
```

Alternative: `export DB_HOST=...` prima di lanciare il processo, oppure `EnvironmentFile=` in systemd (formato `KEY=valore`, una per riga).

---

## 6. Database

**PostgreSQL**, accesso con `asyncpg`. Configurazione in `app.py` (`DB_CONFIG`), usata da:
- un pool di connessioni creato all'avvio (`@app.before_serving`), condiviso con `auth.py` tramite `app.config['db_pool']`;
- una connessione dedicata che esegue `LISTEN log_changes`.

Lo **stesso database** è usato da `clogger` (stesse variabili `DB_HOST`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` nel suo `.env`; `clogger` non legge `DB_PORT`, quindi usa la porta di default 5432).

### 6.1 Creazione DB e utente

```bash
sudo -u postgres psql
```

```sql
CREATE ROLE logme WITH LOGIN PASSWORD 'CambiaMi!';
CREATE DATABASE logme OWNER logme;
\c logme
-- PostgreSQL 15+: lo schema public non è più scrivibile da tutti
GRANT ALL ON SCHEMA public TO logme;
```

Con questo approccio l'utente `logme` è proprietario delle tabelle e ha tutti i permessi necessari (al backend e a `clogger`). Se dai a `clogger` un utente separato, gli servono `SELECT` su `users` e `log`, `INSERT`/`DELETE` su `log` e `USAGE` sulla sequenza `log_id_seq`; inoltre `clogger` usa il tipo `access_direction`, quindi richiede le migrazioni di questo repo.

Se vuoi un utente applicativo con permessi minimi (schema creato da `logme`):

```sql
CREATE ROLE logme_app WITH LOGIN PASSWORD 'AltraPassword!';
GRANT CONNECT ON DATABASE logme TO logme_app;
GRANT USAGE ON SCHEMA public TO logme_app;
GRANT SELECT, INSERT, DELETE ON users, log, managers TO logme_app;
GRANT UPDATE ON managers TO logme_app;            -- non usato dal codice, utile solo per attivare manager
GRANT USAGE, SELECT ON SEQUENCE log_id_seq, managers_id_seq TO logme_app;
```

Se PostgreSQL è su un altro host, abilita l'accesso in `postgresql.conf` (`listen_addresses`) e `pg_hba.conf` (es. `host logme logme 10.0.0.0/24 scram-sha-256`).

### 6.2 Schema / migrazioni

Non c'è un tool di migrazione: gli script SQL in `migrations/` vanno applicati a mano, **in quest'ordine**:

```bash
psql -h localhost -U logme -d logme -f /opt/logme/logMeBE/migrations/001_a_initial.sql
psql -h localhost -U logme -d logme -f /opt/logme/logMeBE/migrations/001_create_managers_table.sql
```

(Se `psql` non può leggere i file in `/opt/logme`, eseguilo con `sudo -u logme` oppure copia gli script in una cartella leggibile.)

Risultato:
- `users(barcode CHAR(13) PK, nome VARCHAR(100), cognome VARCHAR(100), email VARCHAR(255))`, con check su 13 cifre. Attenzione: l'API accetta nome/cognome fino a 255 caratteri, oltre i 100 l'INSERT fallisce con errore 500 (*da verificare/correggere*);
- tipo enum `access_direction ('CHECKIN','CHECKOUT')`;
- `log(id SERIAL, barcode FK -> users, event_time TIMESTAMPTZ default now(), direction)`;
- funzione `notify_log_change()` + trigger `log_change_trigger` (AFTER INSERT/UPDATE/DELETE su `log` -> `pg_notify('log_changes','changed')`);
- `managers(id, username UNIQUE, password_hash, active default false, created_at)`.

Nota: `001_a_initial.sql` usa `CREATE TABLE`/`CREATE TYPE` senza `IF NOT EXISTS`, quindi va eseguito una sola volta.

### 6.3 Stringa di connessione

Il codice non usa una DSN ma i singoli parametri. Equivalente per test manuali:

```
postgresql://logme:CambiaMi!@localhost:5432/logme
```

### 6.4 Attivazione dei manager

`/auth/register` crea il manager con `active = false` e il login restituisce 403 finché non viene attivato. Non esiste un endpoint di attivazione: si fa via SQL.

```sql
UPDATE managers SET active = TRUE WHERE username = 'mario';
```

Massimo 10 manager (controllo in `auth.py`).

---

## 7. Collegamenti con gli altri moduli

### log-me-app (frontend)
- Nel frontend imposta (sono variabili `NEXT_PUBLIC_*`, incluse nel bundle al momento di `next build`):
  - `NEXT_PUBLIC_API_BASE_URL` = URL del backend, es. `http://<server>:5000` o `https://api.example.com`
  - `NEXT_PUBLIC_WS_URL` = `ws://<server>:5000/ws/logs` o `wss://api.example.com/ws/logs` (default nel codice: `ws://localhost:5000/ws/logs`)
- **Autenticazione**: il frontend chiama `/auth/login`, salva il token e lo invia come `Authorization: Bearer <token>` (`log-me-app/src/lib/api/client.ts`). Non c'è refresh token: dopo 24h serve un nuovo login.
- **CORS**: le origini consentite sono fisse in `app.py`:
  ```python
  allow_origin=[
      "http://localhost:3000",
      "http://192.168.1.38:3000",
      "http://192.168.12.158:3000"
  ]
  ```
  In un nuovo server **devi modificare questa lista** aggiungendo l'origine esatta da cui il browser apre il frontend (schema + host + porta, es. `https://logme.example.com`), poi riavviare il servizio. Non è configurabile via env.
  La stessa lista vale anche per il **WebSocket** `/ws/logs`: `quart-cors` rifiuta con **400** l'handshake se l'header `Origin` manca o non è in elenco (anche un client da riga di comando deve inviare un `Origin` consentito).

### clogger
- Nessuna chiamata HTTP: condivide il **database** (stesse credenziali). Inserisce in `log`, e il trigger notifica il backend.
- `cleanup_table` (cron alle 23:59, vedi `clogger/install_cron.sh`) esegue `DELETE FROM log`: ogni notte i log vengono cancellati; il trigger scatta e il Google Sheet viene svuotato.

### Google Sheets
1. Crea un service account in Google Cloud, abilita la Google Sheets API, scarica la chiave JSON.
2. Condividi il foglio con l'email del service account (permesso Editor).
3. Imposta `SPREADSHEET_ID`, `WORKSHEET_NAME`, `SERVICE_ACCOUNT_FILE_NAME`.

Se queste variabili mancano l'API funziona comunque, ma a ogni modifica di `log` il task di aggiornamento fallisce in background (errore nel log).

---

## 8. Sviluppo e test

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt -r requirements-test.txt
nano .env              # nessun .env.example nel repo: usa l'esempio della sezione 5
python app.py          # http://127.0.0.1:5000
# oppure: quart run -h 0.0.0.0 -p 5000   (QUART_APP=app se necessario)
```

### Test

I test (`tests/`, configurati da `conftest.py` e `pytest.ini`) usano un **vero PostgreSQL**. `conftest.py` carica `.env.test` dalla directory corrente.

> **Attenzione**: all'avvio i test fanno `DROP TABLE log, users, managers` e li ricreano. Usa **sempre un database dedicato**, mai quello di produzione.

```bash
sudo -u postgres createdb -O logme logme_test   # o: CREATE DATABASE logme_test OWNER logme;
cat > .env.test <<'EOF'
DB_HOST=localhost
DB_PORT=5432
DB_NAME=logme_test
DB_USER=logme
DB_PASSWORD=CambiaMi!
EOF

pytest tests/ -v
pytest tests/ --cov=app --cov-report=term
```

Lo schema creato dai test (`conftest.py`) è semplificato rispetto a `migrations/` (niente enum né trigger).

### CI
`.github/workflows/ci.yml`: su push a `master`/`develop` (o manualmente) avvia Postgres 15, installa le dipendenze con Python 3.14 ed esegue `pytest tests/ -v`.

---

## 9. Verifica, log e troubleshooting

### Verifica

Non esiste un endpoint di health check; usa gli endpoint pubblici:

```bash
curl -s http://127.0.0.1:5000/users
curl -s http://127.0.0.1:5000/logs
curl -s -X POST http://127.0.0.1:5000/auth/login \
     -H 'Content-Type: application/json' \
     -d '{"username":"mario","password":"..."}'
# test di NOTIFY: dovrebbe arrivare un messaggio sul WebSocket /ws/logs
psql -h localhost -U logme -d logme -c "NOTIFY log_changes, 'test';"
```

### Log

```bash
journalctl -u logmebe -f
```

### Problemi comuni

| Sintomo | Causa probabile |
|---|---|
| Il servizio termina subito con errore di connessione | `DB_*` errate, Postgres non raggiungibile, `pg_hba.conf` |
| `relation "users" does not exist` / `type access_direction does not exist` | Migrazioni non applicate (sezione 6.2) |
| Il browser segnala errore CORS | Origine del frontend non presente in `allow_origin` in `app.py` |
| Login 403 "Account is not active" | Manager da attivare via SQL (sezione 6.4) |
| 401 "Invalid or expired token" dopo un riavvio | `SECRET_KEY` cambiata o token oltre le 24h |
| Il WebSocket non riceve eventi dietro nginx | Mancano gli header `Upgrade`/`Connection` o il trigger `log_change_trigger` |
| Il WebSocket si chiude dopo ~60 s dietro nginx | Aumenta `proxy_read_timeout` |
| Handshake WebSocket rifiutato con 400 | Origine del frontend non presente in `allow_origin` (vale anche per `/ws/logs`) |
| Errore 500 "Non è stato possibile mandare l'email" | Variabili `EMAIL_*` errate, porta senza STARTTLS |
| Google Sheet non aggiornato, errori `gspread`/`google.auth` nel log | Variabili Sheet mancanti, JSON non leggibile, foglio non condiviso con il service account |
| `too many connections` su Postgres | Vedi nota sotto |

**Nota sulle connessioni**: in `app.py` ci sono due funzioni `@app.before_serving` (`startup` e `create_db_pool`) che creano **entrambe** un pool asyncpg (default 10 connessioni ciascuno), più la connessione di `LISTEN`: circa 21 connessioni per processo. Tienine conto in `max_connections`. *Da verificare/correggere nel codice.*

---

## 10. Sicurezza

- **`SECRET_KEY`**: obbligatorio impostarla; con il default `dev_secret_key_change_me` chiunque può forgiare un JWT valido.
- **Permessi file**: `.env` e `service_account.json` con `chmod 600`, proprietario l'utente del servizio. Sono già in `.gitignore`: non committarli.
- **HTTPS**: esponi il backend solo dietro reverse proxy con TLS (`--bind 127.0.0.1:5000`), usa `https://`/`wss://` nel frontend. Il token viaggia nell'header `Authorization`.
- **Endpoint pubblici**: `GET /users` (incluse le **email**), `GET /users/<barcode>`, `GET /logs`, `GET /logs/<id>`, `GET /users/newean`, `/ws/logs` e `/auth/register` non richiedono autenticazione. Valuta di limitarli a livello di rete/reverse proxy se il server è esposto su Internet.
- **Registrazione**: chiunque può registrarsi come manager, ma l'account resta inattivo finché non viene attivato via SQL.
- **Database**: utente dedicato, password robusta, accesso di rete limitato in `pg_hba.conf`; usa un DB separato per i test.
- **CORS**: elenca solo le origini realmente usate.

---

## Punti da verificare

- Compatibilità con versioni di Python diverse dalla 3.14 usata in CI.
- Doppia creazione del pool DB in `app.py` (vedi sezione 9).
- Funzionamento di `SEND_EMAIL_ON_USER_REGISTER`: il codice richiama `send_barcode()` sostituendo la request con un oggetto finto (monkey-patch); non è coperto dai test. Se l'invio email fallisce, l'utente risulta **già creato** ma la risposta è 500.
- Lunghezza nome/cognome: 100 caratteri nello schema di `migrations/`, 255 nella validazione dell'API (e nello schema dei test).
- Nessun health check né configurazione delle origini CORS via env: eventuali miglioramenti al codice.
