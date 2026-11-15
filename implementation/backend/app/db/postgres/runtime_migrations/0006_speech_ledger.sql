-- These fields are added by SpeechGatekeeper._init_db in the local runtime.
-- Cloud instances require a reviewed migration, never runtime schema mutation.
ALTER TABLE usage_reservations ADD COLUMN reservation_id TEXT;
ALTER TABLE usage_reservations ADD COLUMN turn_generation BIGINT NOT NULL DEFAULT 0;
ALTER TABLE usage_reservations ADD COLUMN reserved_stt_sec DOUBLE PRECISION NOT NULL DEFAULT 0.0;
ALTER TABLE usage_reservations ADD COLUMN reserved_tts_chars BIGINT NOT NULL DEFAULT 0;
ALTER TABLE usage_reservations ADD COLUMN uncertain BIGINT NOT NULL DEFAULT 0;
ALTER TABLE usage_ledger ADD COLUMN entry_id TEXT;
ALTER TABLE usage_ledger ADD COLUMN reservation_id TEXT NOT NULL DEFAULT '';
ALTER TABLE usage_ledger ADD COLUMN turn_generation BIGINT NOT NULL DEFAULT 0;
ALTER TABLE usage_ledger ADD COLUMN cache_hit BIGINT NOT NULL DEFAULT 0;
ALTER TABLE usage_ledger ADD COLUMN uncertain BIGINT NOT NULL DEFAULT 0;
UPDATE usage_reservations SET reservation_id=id,reserved_stt_sec=stt_seconds,reserved_tts_chars=tts_chars;
UPDATE usage_ledger SET entry_id=id;

CREATE FUNCTION viva_julianday(input TEXT) RETURNS DOUBLE PRECISION
LANGUAGE plpgsql STABLE AS $fn$
DECLARE instant TIMESTAMPTZ;
BEGIN
 IF input IS NULL THEN RETURN NULL; END IF;
 IF input='now' THEN instant:=CURRENT_TIMESTAMP;
 ELSIF input ~ '^\d{4}-\d{2}-\d{2}([T ][0-9:.]+([Zz]|[+-][0-9:]+)?)?$' THEN instant:=input::timestamptz;
 ELSE RETURN NULL; END IF;
 RETURN EXTRACT(EPOCH FROM instant)::double precision / 86400.0 + 2440587.5;
EXCEPTION WHEN invalid_datetime_format OR datetime_field_overflow THEN RETURN NULL;
END $fn$;
