-- Asterisk telephony: sip_audio media kind + asterisk transport on voice_sessions.
-- Mirrors alembic/versions/20260917_0149_asterisk_telephony.py.
-- Do not apply against a live database from an agent session.

ALTER TABLE interaction_media DROP CONSTRAINT IF EXISTS interaction_media_kind_check;
ALTER TABLE interaction_media ADD CONSTRAINT interaction_media_kind_check
  CHECK (kind IN ('audio','voicemail','transcript_export','redacted_audio','waveform','sip_audio'));

ALTER TABLE voice_sessions DROP CONSTRAINT IF EXISTS voice_sessions_transport_check;
ALTER TABLE voice_sessions ADD CONSTRAINT voice_sessions_transport_check
  CHECK (transport IN ('smallwebrtc','twilio','daily','asterisk'));
