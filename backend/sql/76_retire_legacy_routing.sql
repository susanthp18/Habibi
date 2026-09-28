-- The Routing / Logic builder no longer participates in Voice Studio or the
-- legacy escalation path. Keep old rules and execution evidence queryable for
-- audit, but remove the active table names so retired code cannot write them.
-- The optional KB gap link keeps its historical rule ID as text; no new writer
-- sets it, and it must not constrain deletion/retention of the archive.
ALTER TABLE IF EXISTS analytics_kb_gap_links
  DROP CONSTRAINT IF EXISTS analytics_kb_gap_links_routing_rule_id_fkey;

DO $$
BEGIN
  IF to_regclass('public.routing_rule_executions') IS NOT NULL THEN
    ALTER TABLE public.routing_rule_executions RENAME TO retired_routing_rule_executions;
    COMMENT ON TABLE public.retired_routing_rule_executions IS
      'Historical Routing / Logic execution evidence; no live evaluator.';
  END IF;
  IF to_regclass('public.routing_rules') IS NOT NULL THEN
    ALTER TABLE public.routing_rules RENAME TO retired_routing_rules;
    COMMENT ON TABLE public.retired_routing_rules IS
      'Historical Routing / Logic definitions; no live evaluator.';
  END IF;
END $$;
