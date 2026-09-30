# Write-guard confirmation benchmark

`api/services/workflow/action_confirmation.py` decides, before a promise, a
callback or a dispute is written, whether the customer authorised it, and reads
the identity digits a customer gave as their answer. It reads any language, so
its behaviour is measured here instead of being coded per language.

`cases.json` holds the terms, a read-back per language, the customer's replies
with the verdict each must get, digit answers, and the gate. `not_confirmed`
means `none` or `denied`. The replies Codex found getting past earlier guards
are in it, as are digit answers with numbers that are not the answer.

## Gate

The run exits non-zero if any false confirmation occurs, or if any expected
kind (`confirmed`, `denied`, `not_confirmed`, `digits`) or any language falls
below `gate.min_accuracy` across all repeats. Each check runs under the
engine's own timeout, and a timeout counts as a miss, as it does in a call.
`--self-check` proves the gate rejects a service that refuses everything and
one that confirms everything, with no model.

## Run

From `agentstudio/engine`:

```bash
LLM_PROVIDER=azure LLM_MODEL=gpt-6-luna LLM_ENDPOINT=https://<resource>.openai.azure.com/openai/v1 \
LLM_API_KEY=... python -m evals.confirmation.benchmark --repeat 3
python -m evals.confirmation.benchmark --self-check
```

Run it on the model agents use (prod: `gpt-6-luna`, reasoning none) before
changing the check's prompts or that model, and add cases -- read-backs,
replies and digit answers -- for every language you add. A few cases per
language show the check works there; they do not prove it for every phrasing.
