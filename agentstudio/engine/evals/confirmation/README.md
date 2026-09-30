# Write-guard confirmation benchmark

`api/services/workflow/action_confirmation.py` decides, before a promise, a
callback or a dispute is written, whether the customer authorised it. It reads
any language, so its behaviour is measured here instead of being coded per
language. The same service reads identity digits that were spoken as words.

`cases.json` holds the terms, a read-back per language, and the customer's
replies with the verdict each must get. `not_confirmed` means `none` or
`denied`; the replies Codex found getting past earlier guards are in it.

## Run

From `agentstudio/engine`:

```bash
LLM_PROVIDER=azure LLM_MODEL=gpt-6-luna LLM_ENDPOINT=https://<resource>.openai.azure.com/openai/v1 \
LLM_API_KEY=... python -m evals.confirmation.benchmark --repeat 3
```

It prints each miss, a pass count per language and the number of false
confirmations, and exits non-zero on any false confirmation. Run it before
changing the check's prompt or the model agents use, and add cases for any
language you are adding.
