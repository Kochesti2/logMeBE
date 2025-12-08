CREATE TABLE users (
    barcode CHAR(13) PRIMARY KEY
        CHECK (barcode ~ '^[0-9]{13}$'),
    nome    VARCHAR(100) NOT NULL,
    cognome VARCHAR(100) NOT NULL,
    email VARCHAR(255)
);
CREATE TYPE access_direction AS ENUM ('CHECKIN', 'CHECKOUT');
CREATE TABLE log (
    id SERIAL PRIMARY KEY,
    barcode CHAR(13) NOT NULL REFERENCES users(barcode),
    event_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    direction access_direction NOT NULL
);

--INSERT INTO log (barcode, direction)
--VALUES ('1234567890123', 'CHECKIN');
-- 1. Funzione che manda la NOTIFY
CREATE OR REPLACE FUNCTION notify_log_change()
RETURNS trigger AS $$
BEGIN
    PERFORM pg_notify('log_changes', 'changed');
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- 2. Trigger sulla tabella log
DROP TRIGGER IF EXISTS log_change_trigger ON log;

CREATE TRIGGER log_change_trigger
AFTER INSERT OR UPDATE OR DELETE
ON log
FOR EACH ROW
EXECUTE FUNCTION notify_log_change();