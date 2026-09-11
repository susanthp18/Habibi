-- A connector whose URL the egress guard refused is not "down" — down is a
-- transport fault that opens the circuit and heals when the remote does.
-- A blocked URL heals only when the operator changes it, so it gets its own
-- word on the row instead of staying at whatever the last probe wrote.
ALTER TABLE mcp_connectors DROP CONSTRAINT IF EXISTS mcp_connectors_health_check;
ALTER TABLE mcp_connectors
  ADD CONSTRAINT mcp_connectors_health_check
  CHECK (health IN ('unknown','healthy','degraded','down','blocked'));
