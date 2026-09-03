# noqa-hidden findings

## E402
```
$ check . --select E402 --ignore-noqa --output-format=concise
exit=1

agent_core\canary.py:20:1: E402 Module level import not at top of file
agent_core\providers\registry.py:45:1: E402 Module level import not at top of file
db.py:18005:1: E402 Module level import not at top of file
tests\test_call_vs92cde3f088_regressions.py:28:1: E402 Module level import not at top of file
tests\test_deadair_ignores_a_talking_caller.py:27:1: E402 Module level import not at top of file
tests\test_deadair_ignores_a_talking_caller.py:34:1: E402 Module level import not at top of file
tests\test_flows_dynamic.py:20:1: E402 Module level import not at top of file
tests\test_flows_survive_a_narrow_grant.py:35:1: E402 Module level import not at top of file
tests\test_flows_survive_a_narrow_grant.py:36:1: E402 Module level import not at top of file
tests\test_flows_survive_a_narrow_grant.py:37:1: E402 Module level import not at top of file
tests\test_silent_greeting.py:30:1: E402 Module level import not at top of file
tests\test_turn_start_and_call_identity.py:26:1: E402 Module level import not at top of file
tests\test_turn_start_and_call_identity.py:27:1: E402 Module level import not at top of file
voice\config.py:18:1: E402 Module level import not at top of file
Found 14 errors.

```

## F401/F841/F811
```
$ check . --select F401,F841,F811 --ignore-noqa --output-format=concise
exit=1

agent_core\cards\compile.py:260:41: F401 [*] `agent_core.cards.schema.PoolKind` imported but unused
agent_core\eval\graders.py:125:40: F401 [*] `agent_core.cards.compile` imported but unused
bot_jobs.py:22:23: F401 [*] `pg_errors.PG_UNIQUE_VIOLATION` imported but unused
schemas.py:10:35: F401 [*] `flow_graph.FlowIssue` imported but unused
schemas.py:10:46: F401 [*] `flow_graph.FlowValidation` imported but unused
tests\test_kb_shared_handler.py:69:12: F401 [*] `voice.tools` imported but unused
Found 6 errors.
[*] 6 fixable with the `--fix` option.

```
