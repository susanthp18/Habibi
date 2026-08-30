# Multilingual architecture — design note

**Status:** design proposal — not a committed sprint
**Date:** 21 Aug 2026
**Product:** BigBound AI (Habibi frontend + collections CRM backend)
**Companions:** `agent_transformation_plan.md` (agent factory) · `decision-intelligence-engine.md` (treatment engine) · `agent_transformation_implementation.md` (build spec)

---

## 0. The one-sentence thesis

**Language is not a TTS knob. It is a governed policy dimension — and in this product it belongs beside reco, treatment, and authority, with a decision log, a veto, and a publish gate.**

Everything below follows from that. The existing north star from `agent_transformation_plan.md` —

> Reco: *the LLM does not choose the product — it receives a shortlist that has already passed every gate, and its remaining job is purely linguistic.*

— has an exact analogue here: **the LLM does not choose the language.** It receives a resolved locale that has already passed a regulatory gate, a capability gate, and an eval gate. Its remaining job is purely linguistic *within* that locale.

---

## 1. Why this is a compliance problem, not a UX problem

Three facts set the difficulty floor.

**1.1 — The regulator names the language.** The UAE Central Bank's customer-protection framework requires bilingual Arabic/English documentation and plain-language disclosure, and expects direct debtor communication in Arabic. "Which language did you dial this borrower in" is an auditable fact about a collections contact, not a preference. A system that treats it as config cannot answer the audit.

**1.2 — English-only guardrails do not degrade gracefully; they fail open.** Current research is unambiguous: state-of-the-art runtime guardrails are trained and evaluated almost entirely on English, and unsafe input in another language routinely evades them — translating an English harmful prompt into a low-resource language bypasses frontier-model safety roughly 79% of the time. Our own compliance layer is a set of English regexes (`agent_core/compliance/detectors.py`, `agent_core/lexicon.py`). On a non-English call, every prohibited-language rule scores clean and every mandatory disclosure scores missing. Both directions are wrong, and the second one is worse: it produces a *false* audit record.

**1.3 — Translation is not a shortcut around 1.2.** Safety requirements are written in native legal and policy language. Machine translation does not preserve culturally grounded meaning, idiomatic threat, or regulatory nuance — which is precisely the content compliance detection exists to catch. Any design that pivots compliance through English is buying a false negative rate it cannot measure.

`agent_core/understanding.py` already says this about Hindi, in its own docstring:

> "On a collections line that is a compliance exposure, not a UX rough edge."

The task is to generalise that sentence to *n* languages without generalising the hand-written Hindi solution *n* times.

---

## 2. What exists today (honest map)

### 2.1 Genuinely good bones

| Layer | State | Where |
|---|---|---|
| Per-customer language | Column exists, plumbed to the prompt as `{language}` | `sql/02_customer_account.sql:54` → `db.py:965` → `bot_runtime.py:490` → `prompt_render.py:27` |
| Tuning schema | `stt.language` / `stt.fallback_languages` are free-form BCP-47 strings, **no allowlist** | `agent_core/tuning.py:238` |
| Mid-call switching | Detect → resolve → `STTUpdateSettingsFrame` is fully wired | `voice/safety.py:123` → `voice/bot.py:1328` → `voice/bot.py:1343` |
| Turn critic | A `KIND_LANGUAGE` correction exists ("caller switched, you didn't follow") | `agent_core/turn_critic.py:254` |
| Per-turn language read | An LLM reads caller language off the audio path, on its own deployment/semaphore/breaker | `agent_core/understanding.py` |
| TTS voice catalog | Synced from Azure's **full** voice list with `locale` / `locale_name` — Arabic voices are already in the DB and already searchable | `tts_catalog_sync.py` → `main.py:2695` |
| SSML | `xml:lang` derived from the voice-name prefix; `looks_like_azure_short_name` already matches `ar-AE-FatimaNeural` | `azure_speech.py:263` |
| Flow graph | Nodes carry **English instructions to the model**, not English speech strings | `voice/flows.py:190` |
| Regional parameterisation | Timezone and statutory calling windows are already DB/env-driven, not constants | `agent_core/clock.py:30`, `contact_policy.py:63` |
| Card language field | `CardMouthRef.languages` exists as a declared list | `agent_core/cards/schema.py:69` |

Two of these matter more than the rest.

**The flow graph is instruction-driven, not template-driven.** Voice output is therefore language-portable *for free* — the model can be instructed in English and speak Arabic. The hard-coded English is concentrated in the **text channels** (`agent_core/treatment/enact.py:196`, `promise_fulfillment.py:153`), which is a much smaller surface.

**The disclosure detectors are already dual-sourced.** `missed_recording_notice` and `missed_mini_miranda` check `ctx.disclosures_read` *before* falling back to regex (`detectors.py:97`, `:117`). A structured, language-independent compliance path already exists in the codebase. Section 7 makes it authoritative rather than a fallback — this is the single highest-leverage idea in this document.

### 2.2 The blockers

| # | Defect | Location | Consequence |
|---|---|---|---|
| B1 | `normalize_language` maps 4 locales and `.get(key, Language.EN_IN)` | `voice/tuning_apply.py:32` | Any unmapped locale **silently** transcribes with an English-India recogniser. No error, no log, plausible garbage. |
| B2 | Script detection covers Devanagari + 3 Indic blocks only | `voice/safety.py:40` | Arabic/Cyrillic/CJK produce no signal → **neither** a language switch **nor** the `offer_agent` handoff. The caller is stuck. |
| B3 | `LANGUAGES = {en, hi, hinglish, other}`; prompt says "Callers speak English, Hindi, or a mix" | `agent_core/understanding.py:63` | Every other language collapses to `other`, carrying no routing information. |
| B4 | Turn critic fires only for `{hi, hinglish}` and looks for Devanagari | `agent_core/turn_critic.py:254` | Language drift is never corrected outside Hindi. |
| B5 | Abuse/legal lexicons are English + Hinglish regex | `agent_core/lexicon.py:35`, `:78` | Threats and abuse in other languages **do not escalate**. |
| B6 | Intent + sentiment are English substring matchers | `agent_core/intent.py`, `agent_core/sentiment.py` | Non-English turns score `out_of_scope`, sentiment 0.00 → wrong KB corpus, no suppression, no escalation. |
| B7 | 10 English compliance regexes | `agent_core/compliance/detectors.py:65`+ | A compliant non-English call fails every disclosure rule; a non-compliant one passes every prohibited-language rule. |
| B8 | `r-dnd-disc` has **no** `disclosures_read` escape hatch (unlike its three siblings) | `detectors.py:124` | Even the structured path can't rescue the opt-out rule. |
| B9 | `ScanContext.disclosures_read` is `frozenset[str]` — drops `read_at_sec` | `compliance/context.py:58` | The structured path loses the 30s recording deadline check, even though `interaction_disclosures.read_at_sec` exists (`sql/04_interactions.sql:134`). |
| B10 | `_tokenize` does `re.sub(r"[^a-z0-9\s%]", " ", …)` — strips all non-ASCII | `kb_retrieve.py:192` | Non-Latin queries produce **zero** keyword tokens. All lexical re-ranking, `wants_exclusions`/`wants_coverage` intent, and product-family filtering silently no-op. Pure cosine, nothing else. |
| B11 | `max_completion_tokens: 220` is English-calibrated | `agent_core/tuning.py:24` | Arabic runs ~2–3× the tokens per word. A 220-token cap truncates Arabic replies mid-sentence — and if that sentence is a statutory disclosure, the truncation is a compliance event. |
| B12 | Message copy is hard-coded English f-strings with `₹`, `IST`, RBI framing | `treatment/enact.py:196`, `promise_fulfillment.py:153` | No per-locale content plane at all. |
| B13 | WhatsApp `template_lang` defaults `en_US` | `whatsapp_outbound.py:513` | Meta templates are per-language and separately approved. |
| B14 | SMS body passed raw, no segment accounting | `twilio_sms.py:81` | Arabic forces UCS-2: 70 chars/segment vs 160. Cost ~2×, unpredictable fragmentation. |
| B15 | No frontend i18n; `<html lang="en">`, no `dir`; ~570 physical direction utilities across 348 `.tsx` files | `Habibi/src/routes/__root.tsx:141` | No RTL, no string extraction. |
| B16 | Zero language-varied eval scenarios (15/15 English) | `voice/evals/scenarios/` | No regression signal for any language. |
| B17 | `_fmt_inr` uses Python `f"{n:,}"`; dates via `%d %b %Y` | `promise_fulfillment.py:66` | Western grouping, English month names, hard currency symbol. Not locale-aware. |
| **B18** | **Identity gate does not normalise numeral systems** | `voice/tools.py:625` | **See §2.3 — the most severe defect found.** |
| B19 | PII detectors miss numbers adjacent to Arabic text; masks emit mixed-script digits | `pii_redact.py:43` | Verified PII leak. See §2.3. |
| B20 | PII detector set is India-only (Aadhaar, PAN, `+91`, `HDFC-*`), DOB is DD/MM/YYYY only | `pii_redact.py:42` | No Emirates ID, Saudi National ID, IBAN, or other national ID formats. |

**The pattern:** none of these throw. Every one degrades silently into a plausible-looking wrong answer. That is the property the design has to kill first.

### 2.3 The sharpest defect: numeral systems break the identity gate

This one is worth stating separately because it is empirically verified, it hits the single most compliance-critical ceremony in the product, and it writes a **false audit record**.

`voice/tools.py:625` filters the caller's spoken digits:

```python
digits = "".join(ch for ch in raw if ch.isdigit())
```

Python's `str.isdigit()` returns `True` for Arabic-Indic digits (٠١٢٣٤٥٦٧٨٩, U+0660–0669) and Extended Arabic-Indic (۰۱۲۳, U+06F0–06F9). Verified behaviour:

```
raw = "١٢٣٤"                      # caller correctly says their last four
isdigit kept all:      True        # passes the len(digits) < 4 guard
equals ASCII "1234":   False       # SQL lookup finds nothing
unicodedata.digit():   "1234"      # the fix is one line
```

So an Arabic-speaking caller who states the **correct** digits:

1. passes the placeholder guard (the value looks like four digits),
2. fails `lookup_customer_for_verify` (no row matches `"١٢٣٤"`),
3. has `identity_verifications` written with `failure_reason="no_match"`,
4. repeats twice more, then hits `verify_attempts >= 3` → handoff / call ends.

The system produces a durable compliance record asserting that a caller failed identity verification when they in fact passed it. That is worse than an outage: an outage is visible.

The same normalisation gap runs through `pii_redact.py`. Two verified behaviours there:

```
"بطاقتي1234 5678 9012 3456"   → card detector does NOT match
"card 1234 5678 9012 3456 ok"  → matches
```

Arabic letters are `\w` characters, so the leading `\b` in `r"\b\d{4}[- ]?…"` never fires against an adjacent Arabic word. A card number spoken into a KB question by an Arabic-speaking caller is **persisted in the clear** in `retrieval_logs.query` — precisely the leak the module's own docstring says it exists to close. And when the pattern *does* match Arabic-Indic digits, `_mask_card` re-emits them: `**** **** **** ١٢٣٤`.

**Fix:** a single `lingua/numerals.py` normaliser (`unicodedata.digit()` over the Unicode `Nd` category), applied at every boundary where spoken or transcribed text becomes a comparable identifier — identity, PII, amount parsing, date parsing. One helper, called from four places, in Phase 0.

---

## 3. Design principles

1. **The engine decides the language; the mouth speaks it.** Language resolution is a policy decision with a logged verdict, not an inference the model makes.
2. **Fail closed, loudly.** An unservable language produces a routed event (`language_unsupported` → human handoff), never a silent substitution. B1 is the archetype of what to never do again.
3. **Capability is earned per language, not claimed globally.** "We support 40 languages" is only true at a defined tier. See §5.
4. **Structural evidence beats textual evidence.** Where a fact can be proven by a tool call or a table row, do not prove it with a regex. This makes the mandatory half of compliance language-independent.
5. **Never judge compliance on a translation.** The pivot gloss has a hard boundary (§6.3).
6. **Never machine-translate a statutory disclosure at runtime.** Disclosures are reviewed, signed, versioned artefacts.
7. **Operator locale and customer locale are independent axes.** A Hindi-speaking supervisor may review an Arabic call in an English UI.
8. **Regression is per-language or it is invisible.** An Arabic quality collapse hides inside an aggregate QA score.

---

## 4. The core abstraction: `agent_core/lingua/`

A new policy engine, shaped exactly like the existing ones (`reco/`, `treatment/`, `authority/` all share `config · features · policy · scoring · engine · decisions`):

```
agent_core/lingua/
  registry.py     # LanguagePack discovery, tier resolution, signature check
  features.py     # gather the signals (declared, detected, tenant, channel)
  policy.py       # hard vetoes — regulatory floor, tier floor, channel capability
  engine.py       # resolve() → LanguageDecision
  decisions.py    # persist to language_decisions
  binding.py      # locale → {stt provider+settings, tts voice, token budget}
  bidi.py         # FSI/PDI isolation for interpolated values
  format.py       # CLDR numbers, dates, currency, plural rules
  packs/          # the LanguagePacks themselves
```

### 4.1 `LanguageDecision`

```python
@dataclass(frozen=True)
class LanguageDecision:
    locale: str                  # "ar-AE" — BCP-47, canonical
    script: str                  # "Arab"
    direction: Literal["ltr", "rtl"]
    tier: int                    # 0..3, see §5
    source: str                  # declared | detected | tenant_default | regulatory_floor | fallback
    reason: str                  # human-readable, lands in the audit log
    stt_mode: Literal["fixed", "bilingual", "lid"]
    stt_candidates: tuple[str, ...]
    tts_voice: str | None
    token_multiplier: float      # ar≈2.2, hi≈1.8, en=1.0 — see §6.4
    allows_money_writes: bool    # tier >= 2
    fallback_chain: tuple[str, ...]
```

Persisted to a `language_decisions` table on the same pattern as `treatment_decisions` / `offer_decisions`. This is what makes "which language did we dial this borrower in, and why" answerable.

### 4.2 Resolution order

Deterministic, and every step logs which rule fired:

```
1. REGULATORY FLOOR   tenant jurisdiction mandates a locale for this
                      contact type (UAE: Arabic for statutory notice)
                      → that locale is pinned; a second locale may be
                        added, never substituted
2. DECLARED           customers.language, if servable at required tier
3. DETECTED           live signal from LID / understanding, if it beats
                      declared with confidence and the pack allows switch
4. TENANT DEFAULT     bot_deployments language default
5. FALLBACK CHAIN     pack-declared (ar-AE → ar → en)
6. UNSERVABLE         emit language_unsupported → human handoff.
                      NEVER substitute silently.
```

Step 1 is the one that does not exist anywhere today and is the reason this must be an engine rather than a config lookup.

---

## 5. The LanguagePack — the unit of extensibility

This is the answer to *"the customer might be from any country."*

A LanguagePack is a **signed, versioned artefact** — deliberately shaped like the existing skill packs (`agent_core/skills/packs/*/SKILL.md` with frontmatter, `sign.py`, `lint.py`, `persist.py`), so it reuses the governance machinery rather than inventing a parallel one.

```
agent_core/lingua/packs/ar-AE/
  PACK.yaml            # tier, locale, script, direction, plural rules,
                       # token_multiplier, fallback_chain, dialect notes
  stt.yaml             # provider binding, model, candidate set, mode
  tts.yaml             # voice per persona style (empathetic/firm/brisk)
  lexicon/
    abuse.yaml         # native patterns — NOT translated from English
    legal.yaml
    distress.yaml
  disclosures/
    recording.icu      # legally reviewed, signed, versioned
    mini-miranda.icu
    opt-out.icu
  messages/            # ICU MessageFormat catalogs for SMS/WA/email
  glossary.yaml        # do-not-translate: brand, product names, ref formats
  evals/               # scenario pack; must pass to hold the claimed tier
  SIGNATURES           # who reviewed what, when
```

### 5.1 Tiers — the governance idea

| Tier | Name | Capability | Gate to reach it |
|---|---|---|---|
| **0** | Unsupported | Detect and hand off to a human. Never speak. | none — this is the safe default for every locale on earth |
| **1** | Understand | Converse, answer, capture intent. **No money writes. No statutory disclosure.** Inbound informational only. | STT+TTS binding exists; smoke evals pass |
| **2** | Transact | Full collections. Money writes allowed. | Disclosures legally reviewed **and signed**; native lexicon present; full eval suite passes in-language; red-team pass |
| **3** | Regulated primary | Dialect-tuned; per-regulator disclosure set; human QA sampling in-language | Tier 2 + sustained in-language QA coverage + regulator sign-off |

**This is what lets you honestly say "any country" on day one.** Tier 1 across dozens of languages is achievable immediately and is genuinely useful — the bot understands, answers policy questions, and hands off cleanly. Tier 2 is earned language by language as legal signs off. You cannot legally transact in a language nobody has reviewed, and the tier makes that constraint mechanical instead of aspirational.

### 5.2 The publish gate

`agent_core/cards/schema.py:69` already has `CardMouthRef.languages` — today a decorative `["English", "Hindi"]`. Promote it:

```yaml
mouth:
  languages:
    - locale: en-IN
      tier: 2
    - locale: ar-AE
      tier: 2
    - locale: hi-IN
      tier: 2
    - locale: ml-IN
      tier: 1      # understand + handoff only
```

`agent_core/cards/compile.py` refuses to publish when a card claims a tier the pack does not hold, or whose eval subset has not passed. This is the exact analogue of `EVAL_GATE_ENABLED` in `agent_core/platform_flags.py:41` — same shape, same discipline, new axis.

---

## 6. Layer-by-layer design

### 6.1 The ear (STT)

Three modes, chosen per pack rather than hardcoded:

| Mode | When | Provider notes |
|---|---|---|
| `fixed` | Declared locale, high confidence | Lowest latency. Current behaviour, made explicit. |
| `bilingual` | Code-switching is the norm (GCC Arabic↔English, Hinglish) | **Speechmatics** ships a purpose-built Arabic–English bilingual model: 6.3% WER on code-switching (~35% fewer errors than the nearest competitor at 9.7%), 4.5% Arabic-only, Gulf/Egyptian/Levantine + MSA, sub-second, and **on-prem / on-device deployable**. Pipecat already has `SpeechmaticsSTTService`. |
| `lid` | Language genuinely unknown | Azure at-start LID (≤4 candidates, <5s) or continuous LID (≤10, Python SDK). |

**Critical constraint to design around:** Azure's continuous LID *explicitly does not detect language change within a sentence*. Intra-sentence code-switching — which is exactly what Hinglish and Gulf Arabic conversation *is* — is not solvable with LID. It needs a bilingual model. This is why `bilingual` is a first-class mode and not a variant of `lid`.

**Second constraint:** Azure LID permits only one locale per base language (no `en-US` *and* `en-GB` as candidates). The candidate-set builder in `binding.py` must enforce this or the SDK rejects the config.

**The B1 fix, precisely:** `normalize_language` stops being a 4-entry dict with a default. It becomes a resolution against the pack registry that **raises `UnsupportedLocale`** on a miss. The caller (`voice/bot.py:1343`) catches it and emits `language_unsupported` → handoff. One silent corruption becomes one routed event.

**Provider abstraction:** `lingua/binding.py` returns `(service_class, settings)` so the Pipecat STT service is selected per pack. Pipecat's multilingual conventions differ by provider and must be encoded in the pack, not in `bot.py`: Whisper-family and ElevenLabs use `language=None` for auto-detect; Deepgram uses `language="multi"`; Google takes a list; Soniox takes `language_hints` + `enable_language_identification`.

### 6.2 The mouth (TTS)

Mostly already works. `tts_catalog_sync.py` has the full Azure catalog with locales; Azure covers ~20 Arabic regional locales (ar-SA, ar-AE, ar-EG, ar-LB, ar-OM, ar-IQ, ar-MA…) with named neural voices, and `build_ssml` already derives `xml:lang` from the voice name.

What's needed:
- **Voice binding per pack per persona style.** `tts.yaml` maps `empathetic|brisk|firm` → a concrete `ar-AE-*Neural`.
- **Style capability is locale-dependent.** `azure_speech.py:195` hardcodes an `mstts:express-as` capability list that is all `en-US`/`en-IN`. Arabic voices support a different style set — the pack must declare it, or `_warmth_express_as` silently drops all expressiveness.
- **No-voice fallback ladder:** preferred voice → same-language alternate → parent locale → **Tier 0 handoff**. Never a wrong-language voice.
- On-prem note: Azure ships containerised STT and Neural TTS from MCR for disconnected deployment (commitment plan + approval required). Speechmatics offers on-prem and on-device. Both are consistent with the on-prem target.

### 6.3 Understanding — the pivot gloss, with a hard boundary

`agent_core/understanding.py` already produces `english_gloss`. Keep it. Bound it.

| Gloss is **allowed** for | Gloss is **forbidden** for |
|---|---|
| Intent routing | Compliance detection |
| KB query planning | Abuse / legal escalation |
| Sentiment trend | Consent capture |
| Analytics, supervisor UI | The verbatim audit record |

Rationale is §1.3. The gloss is a *convenience* representation for routing; it is not evidence. Encode the boundary as a type, not a comment: compliance detectors take `NativeText`, routing takes `GlossedText`, and the two do not implicitly convert.

Also: widen `LANGUAGES` (B3) from a 4-value enum to a validated BCP-47 string against the pack registry, and rewrite the prompt at `understanding.py:103` to name the tenant's actual configured set rather than "English, Hindi, or a mix".

### 6.4 Token budget — a real, unglamorous blocker

Arabic runs roughly **2–3× the tokens per word** of English on English-first tokenizers (~2.4 tok/word vs ~1.5–1.6). This is not a rounding error; it hits four places:

1. **`max_completion_tokens: 220`** (`agent_core/tuning.py:24`) truncates Arabic replies mid-sentence.
2. **KB chunking** (`kb_chunking.py`, `chunk_size=512` tiktoken tokens) yields Arabic chunks with ~⅓ the semantic content of English ones — retrieval quality drops for reasons that look like a model problem and are actually a chunker problem.
3. **Cost.** ~70%+ premium per equivalent message; `usage_meter.py` attributes it to nothing in particular.
4. **Latency.** More output tokens = later last-audio, on a channel where turn latency is the product.

**Fix:** `token_multiplier` in `PACK.yaml`, applied at `build_llm_settings_kwargs` (`voice/tuning_apply.py:227`), at the chunker, and at the meter. Operators tune one number in English and the pack scales it. Non-Latin chunking should measure in characters or a script-aware budget rather than cl100k tokens.

### 6.5 Compliance — three tiers of detection

The hardest layer, and the one with the most leverage available.

**Tier A — structural (language-independent). Do this first.**

`interaction_disclosures` already exists (`sql/04_interactions.sql:129`) with `read_at_sec`, and `voice/persist.py:986` already writes it from the `disclose_recording` tool. The detectors already consult it (`detectors.py:97`, `:117`). Three changes make it authoritative:

1. **`ScanContext.disclosures_read` becomes a mapping** `rule_id → read_at_sec` instead of `frozenset[str]` (B9, `compliance/context.py:58`). The 30s recording deadline then applies on the structured path too — today it only applies on the regex path, so the structured path is *more* permissive than intended.
2. **`r-dnd-disc` gains the checklist check** its three siblings have (B8, `detectors.py:124`).
3. **Every mandatory disclosure gets a tool.** Where a rule has no tool, add one. A tool call is language-independent proof; a regex over transcript text is not.

Result: **the mandatory half of compliance stops depending on language at all.** This is the highest-value change in the document and it is small.

**Tier B — native lexicon packs.**

`agent_core/lexicon.py` becomes the `en` pack rather than *the* lexicon. Its hard-won narrowing discipline is preserved and generalised — that file's docstring records that `\bkill\b` had to become `kill\s+(?:you|yourself)` and `\bfir\b` needed police context because *fir* is Hinglish for "then". Every language will develop its own list of exactly this kind of scar. Pack lexicons are authored natively, reviewed, and signed — never translated from English.

**Tier C — LLM judge, in-language, for what lexicons miss.**

Prohibited language, threat, and distress need judgement. Run an in-language judge on the existing **analysis profile** (`understanding.py` already has this: own deployment, own semaphore, own circuit breaker, off the audio path). Merge with the identical rule already used there:

> `abuse` and `legal` are `keyword OR llm` — an LLM must never be able to suppress a compliance escalation the deterministic path already found.

Research supports the tier ordering: LLM classifiers on non-English input outperform maintaining multilingual regex, at roughly 150ms — affordable off the audio path, unaffordable on it. Which is exactly where `understanding.py` already put it.

**Tier D — QA scorecards per language.** `live_qa/scorecard.py` aggregates. Split the aggregate by locale or an Arabic collapse is statistically invisible next to English volume.

### 6.6 The content plane (text channels)

The one place where hard-coded English actually lives.

- **New table `message_templates`**: `(template_key, locale, version, status, body_icu, reviewed_by, signed_at)`. ICU MessageFormat — plural categories vary by language (Arabic has six: zero/one/two/few/many/other; English has two). String concatenation cannot express this; ICU can.
- **`treatment/enact.py:196` `_copy()` and `promise_fulfillment.py:153` become template lookups.** Note the current docstring — the copy is composed in code specifically so a new channel *cannot* ship without the statutory elements. Preserve that: the template **schema** enforces required slots (regulated entity, loan reference, grievance route); the pack supplies the wording.
- **Bidi isolation is mandatory.** Every interpolated number, account tail, date, currency amount, and URL wrapped in `FSI … PDI` (U+2068/U+2069). Without it, the Unicode bidirectional algorithm reorders neutral characters adjacent to Arabic text and an account tail or amount can render transposed. In a collections notice that is a **mis-stated debt**, not a typo. Isolates are the modern mechanism and are preferred over LRM/RLM marks because they do not leak into surrounding text.
- **Formatting via CLDR** (`lingua/format.py`), replacing `_fmt_inr` (B17) and `%d %b %Y`. Currency symbol, grouping, decimal separator, calendar, and numeral system (Arabic locales may use Eastern Arabic-Indic digits ٠١٢٣) all come from the locale.
- **No reviewed template → do not send.** Fall back to the tenant's statutory language and log `template_locale_fallback`. Never machine-translate and dispatch.
- **WhatsApp** (B13): per-locale approved template names in the pack, not one env var.
- **SMS** (B14): segment accounting in `twilio_sms.py`. Non-GSM-7 content is UCS-2 at 70 chars/segment. Compute and log segments; warn above a threshold.

### 6.7 Identity, PII, and numerals

The layer §2.3 exposed. Three components, all small, all Phase 0 or 1.

**`lingua/numerals.py` — one normaliser, four call sites.** Fold every Unicode `Nd` digit to ASCII via `unicodedata.digit()` before any comparison, lookup, or mask. Call sites: `voice/tools.py:625` (identity), `pii_redact.py` masks, spoken-amount parsing, spoken-date parsing. Store normalised, *display* in the locale's numeral system via `lingua/format.py` — never the reverse.

**PII detectors move into the pack.** `pii_redact.py`'s docstring correctly notes that its detector set is mirrored by frozen copies in `Habibi/src/data/redaction-seed.ts` and two seed migrations, since an applied migration must not import live code. That constraint survives: packs ship detector sets, and the migration copies are generated from the pack at build time rather than hand-maintained. Per-pack detectors carry national ID formats (Emirates ID, Saudi National ID, IBAN, national card schemes) rather than assuming Aadhaar/PAN.

**Boundary matching must be script-aware.** `\b` is the wrong tool once identifiers can abut Arabic, Devanagari, or CJK word characters. Detectors need lookarounds against a script-aware character class, and every pack's detector set needs a test fixture with the identifier embedded in native text — the case that currently fails.

**Names are a separate, harder problem — scope it explicitly.** Identity today is digits-only (`phone_match`, `account_tail`), which is fortunate: name matching across transliterations (Mohammed / Muhammad / Mohamed / محمد) is a genuinely hard matching problem and should stay out of the identity gate. If a future card wants name-based verification, it needs a transliteration-aware matcher and its own review — do not let it arrive by accident through a prompt change.

### 6.8 Latency and cost budget

Voice is a latency product; every choice in §6.1 spends from the same budget.

| Decision | Latency effect | Mitigation |
|---|---|---|
| At-start LID | Azure detects within the first few seconds; **initial** latency rises materially | Use only when locale is genuinely unknown. Declared locale → `fixed` mode, zero cost. |
| Continuous LID | Ongoing overhead + requires `SpeechConfig` from endpoint | Reserve for genuinely multilingual inbound lines. |
| Bilingual model | Sub-second, single pass — **no LID penalty** | Preferred where code-switching is the norm; it is both more accurate *and* cheaper in latency than LID. |
| Arabic token inflation | 2–3× output tokens → later last-audio | `token_multiplier` (§6.4); consider tighter `max_completion_tokens` *in words*, scaled per pack. |
| In-language LLM judge (§6.5 Tier C) | ~150 ms | Off the audio path on the analysis profile — already architecturally solved by `understanding.py`. |

Two budget rules worth writing into the pack schema: a pack declares its **measured** p50/p95 turn latency, and a tier promotion cannot regress the tenant's SLO. Otherwise "we added Arabic" quietly becomes "voice got slower" with no owner.

**Cost:** `usage_meter.py:642` already notes Azure prices STT per tier rather than per locale, so STT cost is locale-neutral. LLM cost is not — the 2–3× token inflation is a real per-locale margin difference and belongs in the meter's attribution, not discovered in a monthly invoice.

**Data residency.** Worth naming because it interacts with §6.1's provider choice: routing Arabic PII to a new cloud STT vendor is a data-transfer decision, not just a quality one. Both candidate providers offer on-prem/container deployment (Azure Speech containers from MCR; Speechmatics on-prem/on-device), which is consistent with the on-prem target — but the pack must declare where a locale's audio is processed, and the tier gate should require that declaration.

### 6.9 Knowledge (RAG)

- **Fix `_tokenize` first** (B10, `kb_retrieve.py:192`). One regex change from ASCII-only to Unicode-aware restores lexical re-ranking for every non-Latin script. Currently non-Latin queries silently lose all keyword boosting, both intent heuristics, and product-family filtering.
- The English `STOP` set and the `wants_exclusions` / `wants_coverage` / `product_tokens` keyword lists move into the pack.
- **`locale` on `kb_documents` and `kb_chunks`.** Retrieve with a locale preference and an explicit cross-lingual fallback; record which locale answered.
- **Cross-lingual answering is allowed, and must be disclosed.** Answering an Arabic question from an English policy document is often correct — the policy exists once. But the retrieval log must record source language ≠ answer language so legal can review the class of answer, and the `_draft_system_prompt` must instruct the model to preserve exact figures, limits, and exclusions across the language boundary.
- Script-aware chunk sizing (§6.4).

### 6.10 Customizability and the agentic layer

This is where the design has to fit what already exists rather than replace it.

- **Skills gain locale overlays.** A skill keeps one `SKILL.md` (instructions to the model, English, portable) plus optional `i18n/<locale>/` overlays carrying objection banks, gold dialogues, and never-say lists in-language. `ptp-negotiate` reasons identically in Arabic; the *objections* ("راتبي تأخر") and the phrasing that works are locale-specific. Forking a skill per language would fragment the procedure — overlays keep one procedure, many voices.
- **The Agent Card declares locale×tier** (§5.2) and `compile.py` enforces it.
- **Handoff carries locale.** `handoff_to_agent` payloads include the resolved `LanguageDecision`, or the receiving specialist restarts the language negotiation and the caller repeats themselves.
- **Mesh roles** (`voice/mesh_roles.json`) gain a language-specialist axis so "hand to someone who speaks Levantine Arabic" is a typed handoff, not a prompt hint.
- **Memory.** `agent_core/context.py:323` already carries `language` in the persona block, and the customer memory described in the transformation plan should carry *observed* language separately from *declared* — a customer whose CRM row says English but who has spoken Arabic on the last three calls is a data-quality signal worth writing back.
- **MCP.** Add `policy://language-tiers` as a resource so an external client can see what is servable before asking for it, consistent with the existing `policy://authority-matrix` plan.

### 6.11 Frontend

- `react-i18next` + ICU; string extraction across 348 `.tsx` files.
- `dir` on `<html>` (`__root.tsx:141`) driven by the **staff** locale; CSS logical properties throughout.
- **Codemod ~570 physical utilities** (`ml-`×119, `mr-`×99, `text-left`×73, `left-`×61, `pl-`×42, `border-l`×42, `right-`×28, `border-r`×25, `pr-`×23) → `ms-`/`me-`/`text-start`/`start-`/`ps-`/`border-s`/`end-`/`border-e`/`pe-`. Logical properties handle roughly 80% of RTL layout automatically and browser support has been universal for years.
- **Add `scripts/check-logical-properties.mjs`** to the existing `lint` script, mirroring `check-spacing-scale.mjs` — the repo already has this convention, so reuse it to stop regressions rather than inventing a new gate.
- **Transcript rendering:** per-turn `dir="auto"`, native text primary, gloss secondary and visibly labelled as a gloss.
- **Two independent axes:** staff locale (chrome) and customer locale (content). Do not couple them.

### 6.12 Evals and observability

- **Locale axis on every scenario.** `voice/evals/scenarios/*.yaml` gain `locales: [en-IN, ar-AE]`. Today 15/15 are English (B16).
- **Code-switch scenarios explicitly** — the real failure mode, and the one LID cannot cover.
- **Cross-lingual red-team**: the 79%-bypass finding is a test case, not trivia.
- **Publish gate**: card claims `ar-AE` Tier 2 → the `ar-AE` eval subset blocks publish.
- **`language` as a first-class dimension** on interactions, transcript turns, tool calls, QA scores, treatment decisions, and usage records.
- **New events**: `language_resolved`, `language_switched`, `language_unsupported`, `template_locale_fallback`, `tier_downgrade`, `sms_segments_exceeded`.
- **The trace zipper** from the transformation plan gains a lane: `who (agent/skill) → what language (+ why) → why (engine verdict) → what tool → human gate → outcome`.

### 6.13 Peripheral surfaces — mostly fine, three exceptions

Audited so the plan does not miss a channel:

| Surface | Verdict |
|---|---|
| **AMD / voicemail detection** (`voice/amd.py:58`) | ✅ Event-driven via Pipecat/Twilio (`_on_human` / `_on_voicemail`), not keyword-based. Language-portable as-is. |
| **`voicemail_script`** (`voice/amd.py:25`) | ❌ Hard-coded English f-string. Already tenant-parameterised (agent, issuer) but not locale-parameterised. **Belongs in the content plane (§6.6)** — a voicemail is an unattended statutory contact and is the *worst* place to leave the wrong language. |
| **IVR navigation** (`voice/ivr.py:95`) | ⚠️ `IVRNavigator` is LLM-driven with a natural-language goal, so it is portable — but the *target* IVR will speak the local language and `ivr_goal` is English. Needs a locale hint in the prompt and its own eval scenarios per locale. |
| **DTMF aggregation** (`voice/ivr.py:71`) | ✅ Keypad digits are ASCII by construction. No exposure. |
| **Document ingest** (`agent_core/vision.py:24`) | ⚠️ `_classify` is filename/MIME-based, so classification is safe — but OCR quality on Arabic-script documents is a separate, unvalidated question. Scope explicitly; do not assume. |
| **QA autoscore** (`qa_autoscore.py:138`) | ⚠️ LLM + rubric, so nominally portable — but it scores a non-English transcript against an **English rubric**, and nothing measures whether that holds. Rubrics need locale variants, or at minimum per-locale agreement measurement against human scores (`agent_core/eval/disagreement.py` already exists for exactly this shape of check). |

**Data migration.** `customers.language` is free text today (`"English"`, `"Hindi"`, `NULL` → defaulted to `"English"` at `db.py:1019`). Phase 1 needs a backfill to canonical BCP-47 plus a `NULL`-means-unknown semantic — because "unknown" and "English" are different facts, and conflating them is what makes the resolution ladder in §4.2 silently skip step 2. Keep the free-text column as `language_declared_raw` for audit rather than overwriting it.

---

## 7. Phasing

| Phase | Scope | Rough size |
|---|---|---|
| **0 — Stop lying** | **B18 (numeral normalisation — do this first)**, B19 (script-aware PII boundaries), B1 (no silent EN_IN), B2 (Unicode script detection), B10 (Unicode tokenize), unsupported→handoff path, B11 (token multiplier). No new capability; converts silent corruption into routed events. | ~1 week |
| **1 — Lingua engine** | `agent_core/lingua/`, pack registry, `LanguageDecision` + `language_decisions` table, Tier 0/1 for a broad locale set, card `languages` becomes locale×tier (declarative only). | ~2–3 weeks |
| **2 — Compliance restructure** | Tier A structural detection (B8, B9, disclosure tools), pack lexicons, in-language LLM judge, per-language QA split. **Blocks Tier 2 for any language.** | ~2–3 weeks |
| **3 — First Tier 2 language** | `ar-AE` end to end: bilingual STT binding, TTS voices + style caps, reviewed disclosures, ICU templates, bidi, CLDR formatting, WhatsApp templates, SMS segments, eval pack. | ~3–4 weeks |
| **4 — Knowledge + evals** | KB locale tagging, cross-lingual retrieval + disclosure, script-aware chunking, locale axis in evals, publish gate live. | ~2 weeks |
| **5 — Frontend** | i18n extraction, RTL codemod, lint gate, transcript rendering. Parallelisable with 2–4. | ~2–3 weeks |
| **6 — Scale** | Second and third packs, tenant/community-authored packs, dialect tiers, `policy://language-tiers` over MCP. | ongoing |

Phase 0 is worth doing regardless of whether the rest is funded — it is small, and it converts the current failure mode from "wrong answer that looks right" to "explicit event".

---

## 8. Non-goals — say these out loud

- **No runtime machine translation of statutory disclosures.** Reviewed, signed, versioned, or not sent.
- **No silent language fallback.** Ever. B1 is the bug this whole document is organised around.
- **The LLM does not choose the language.** The engine decides; the mouth speaks.
- **No compliance judgement on translated text.** The gloss is for routing.
- **No "we support N languages" without a tier.** The number without the tier is marketing.
- **No per-language agent forks.** Skills get locale overlays; the procedure stays single-sourced.
- **No language switching mid-sentence via LID.** It does not work; use a bilingual model or don't claim it.

---

## 9. Open decisions

These need a human call and change the shape of Phases 1–3:

1. **Which languages, at which tier, for the first release?** Drives pack authoring cost directly and is the single largest scope lever.
2. **STT provider for bilingual mode.** Speechmatics has the strongest Arabic–English code-switching numbers and on-prem support, but it is a second vendor alongside Azure. Staying Azure-only means accepting that intra-sentence code-switching is not served.
3. **Dialect granularity for Arabic.** One `ar` pack, or `ar-AE` / `ar-SA` / `ar-EG` separately? Affects TTS voice choice, lexicon authoring, and disclosure review count. Gulf vs Egyptian vs Levantine are not interchangeable for a collections script.
4. **Who signs a disclosure pack?** Tier 2 is gated on legal sign-off. That workflow does not exist yet and is the long pole for every new language.
5. **Does the operator UI ship RTL, or only the customer-facing content plane?** Phase 5 is the largest volume of work and the lowest compliance risk — it can lag.

---

## 10. Bottom line

The architecture is already the right shape. Language preference is plumbed end to end, mid-call switching works, the voice catalog is already global, the flow graph is instruction-driven rather than template-driven, and — critically — the compliance layer already has a structured, language-independent evidence path that is currently used only as a fallback.

What is missing is that **language was never promoted to a governed dimension**. It is a string in a config dict with an English default, so every layer that reads it degrades silently rather than failing loudly.

The work is: make it an engine, give it a decision log, gate capability behind tiers, make compliance structural where it can be and native where it cannot, and never substitute a language without saying so.

Do Phase 0 regardless. It is a week, and it is the difference between "we don't support Arabic" and "we support Arabic badly without telling anyone".

---

## Sources

- [Azure — Implement language identification](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/language-identification) — at-start (≤4) vs continuous (≤10) LID; no intra-sentence switching; one locale per base language
- [Azure — Speech containers overview](https://github.com/MicrosoftDocs/azure-ai-docs/blob/main/articles/ai-services/speech-service/speech-container-overview.md) — on-prem / disconnected STT + Neural TTS
- [Azure — Arabic voice pronunciation improvements](https://techcommunity.microsoft.com/blog/azure-ai-foundry-blog/azure-ai-voices-in-arabic-improved-pronunciation/4360306) — ~20 Arabic locales
- [Pipecat — Speech-to-text guide](https://docs.pipecat.ai/pipecat/learn/speech-to-text) — per-provider multilingual conventions
- [Pipecat — Speechmatics STT service](https://docs.pipecat.ai/api-reference/server/services/stt/speechmatics) · [Soniox STT](https://docs.pipecat.ai/api-reference/server/services/stt/soniox) · [Service settings / `STTUpdateSettingsFrame`](https://docs.pipecat.ai/guides/fundamentals/service-settings)
- [Speechmatics — Arabic–English bilingual model](https://www.speechmatics.com/company/articles-and-news/arabic-english-bilingual-speech-to-text) — 6.3% CS WER, 4.5% Arabic-only, Gulf/Egyptian/Levantine, on-prem
- [Benchmarking Commercial ASR Systems on Code-Switching Speech: Arabic, Persian, German](https://arxiv.org/abs/2605.19069) — CS WER comparison; WER over-penalises transliteration ~3×
- [Benchmarking LLM Guardrails in Handling Multilingual Toxicity](https://arxiv.org/html/2410.22153v1) · [Why Do Safety Guardrails Degrade Across Languages?](https://arxiv.org/html/2605.17173v1) · [ML-Bench&Guard](https://arxiv.org/pdf/2605.00689) — translation-based safety loses regulatory nuance; English-only guardrails fail open
- [W3C — Unicode controls for bidi text](https://www.w3.org/International/questions/qa-bidi-unicode-controls.en.html) — isolates (FSI/PDI) preferred over LRM/RLM
- [Frontend Internationalization 2026: ICU, RTL, Locale Routing](https://www.techinterview.org/post/3233475402/frontend-internationalization-2026-icu-rtl-locale-routing/) · [RTL Support: CSS and React](https://better-i18n.com/en/blog/rtl-support-css-react-guide/)
- [LLM Tokenization Explained: English vs Other Languages](https://promptcost.org/en/blog/llm-tokenization-explained/) · [Tokenizer Efficiency Across Arabic LLMs](https://hosn.om/blog/tokenizer-efficiency-arabic-llm.html) — Arabic 2–3× token inflation
- [UAE Central Bank enhances customer protection framework](https://www.pinsentmasons.com/out-law/news/uae-central-bank-sme-customer-protection-framework) — bilingual Arabic/English disclosure requirement
- [SAMA — Debt Collection Regulations for Individual Customers](https://rulebook.sama.gov.sa/en/debt-collection-regulations-and-procedures-individual-customers-0)
