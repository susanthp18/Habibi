# One run-up, built once per turn, passed to every per-turn judgment

---
Status: accepted
---

Two functions decide what a customer meant — `agent_core.understanding.analyze_turn`
and `agent_core.tools.kb_plan.plan_retrieval` — and both shipped taking a `recent`
run-up that **no text-channel caller ever supplied**. Voice built one by hand in
`voice/crm_sink.py` and passed it to the first of them only. So on WhatsApp both
judged a single sentence in isolation, and on voice retrieval did.

This was not theoretical. On 2026-09-11 a customer spent four turns on travel
insurance and then wrote *"nono... better yourself tell me the benefits"*. With no
thread behind it, that classifies as `help_capabilities` and plans as a product
catalog lookup, and the bot answered by listing what it could help with. Measured
in this tree, on the corpus that was live at the time:

```
analyze_turn("nono... better yourself tell me the benefits")
    no run-up    -> help_capabilities
    with run-up  -> product_faq

analyze_turn("international trip and i am traveling from september 23 to 28th 2026")
    no run-up    -> hardship          # a date range, read as an inability to pay
    with run-up  -> product_faq
```

Both match the live logs exactly. The benefits the customer was asking for retrieve
at 0.649–0.692 and always did; what was missing was the four turns that say
*benefits of what*.

`agent_core/understanding.py` already contained a narrow patch for this — it
re-sticks an `out_of_scope` verdict to a live product thread — carrying the comment
*"The LLM sees one turn, not the thread, so this rule still has to live outside
it."* The author knew. The fix is to stop that being true, not to widen the patch to
the other fourteen intents.

## Decision

The thread is fetched **once per turn, before anything judges the turn**, and the
same snapshot is handed to every consumer: the classifier, the retrieval planner,
the tools, and the prompt. `agent_core.compaction.run_up` owns the projection and
the one rule that is easy to get wrong twice — the turn under test is not part of
its own context.

## Considered options

**Pass `recent` at each call site.** Rejected, and it is the obvious one. There are
five call sites across three channels and four different history shapes (`role`/
`content`, `role`/`text`, tuples, and a bot-only `list[str]`), so "pass the
argument" is really "write four adapters and keep them agreeing". It also could not
have been done at the site that mattered: on the text channel the history loaded
143 lines *after* classification, and the fetch size was narrowed using the intent
that classification produced. The ordering was the bug; an argument does not fix an
ordering.

**Persist the run-up on `conversations.bot_state`.** Rejected. It is a hot jsonb row
rewritten every turn, the transcript already lives in `messages`, and the inbox
reset clears the key — so the classifier's context would vanish on a code path that
knows nothing about classification.

**Re-query per consumer.** Rejected as what we already had. `bot_runtime` was
issuing three separate reads of `messages` per turn — the latest customer row, the
last four customer bodies for the product hint, and the prompt history — which is
three chances for three components to disagree about what was said.

## Consequences

**One fewer query per turn, not one more.** The three reads collapse to the
latest-row lookup plus one windowed fetch. The per-intent narrowing that used to
size the fetch now slices the list afterwards; the rows are identical either way,
because both paths take the newest `hist_limit * 4`.

**A dialog reset now clears the product hint too.** The hint used to re-query
without the reset filter, so a product named before a reset survived it. Deliberate:
a reset means forget, and a hint that outlives one is how a stale product leaks into
a fresh conversation.

**The intent label is demoted from an instruction to a hint.** Context makes the
classifier better, not infallible, so `_dialog_control_block` no longer opens with
"highest priority" and no longer tells the model to recite its capabilities whenever
a turn is labelled `help_capabilities`. The customer's own words outrank the label.
The `out_of_scope` carry-forward in `_merge` is now redundant but is left in place —
it is the fallback when the LLM path is disabled, where there is still no thread.

**The sandbox pays one small query it did not pay before**, inside the enrichment
worker thread rather than on the turn, so the prefetch keeps the overlap it exists
for.

**Voice gains what it already had.** `CrmSink` has kept an interleaved buffer of
both speakers since it was written and handed it to the classifier every turn.
Retrieval now reads it through a public `run_up()` accessor rather than a private
attribute. The comment at the voice retrieval call site — *"No customer turn is
available here"* — was true of the function's arguments and never true of the call.
