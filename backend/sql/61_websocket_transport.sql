-- Sandbox Live over a WebSocket: `websocket` on voice_sessions.transport.
-- Mirrors alembic/versions/20260925_0157_websocket_transport.py.
--
-- The browser's voice path on a server with no UDP route (voice/sandbox_ws.py).
-- Recording it as `smallwebrtc` would make every session row lie about how the
-- audio travelled, which is the first thing a latency investigation reads.

ALTER TABLE voice_sessions DROP CONSTRAINT IF EXISTS voice_sessions_transport_check;
ALTER TABLE voice_sessions ADD CONSTRAINT voice_sessions_transport_check
  CHECK (transport IN ('smallwebrtc','websocket','twilio','daily','asterisk'));
