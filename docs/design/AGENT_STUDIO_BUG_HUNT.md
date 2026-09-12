# Agent Studio — tab-by-tab bug hunt report

Date: 2026-08-25 (session date)
Scope: every Agent Studio surface — Fleet index (`/agent-studio`), the card editor's 15 internal
tabs (`/agent-studio/$botId`, which renders `PromptStudioPage`), Skills library
(`/agent-studio/skills`) and Skill detail (`/agent-studio/skills/$skillId`).
Nothing in the repo was modified; this is a read-only audit deliverable.

## Method and confidence labels

No GUI browser driver exists in this harness, so the brute-force pass combined:

- full line-level reads of every tab component, its API client modules and the matching
  backend handlers (`backend/main.py`, `backend/db.py`, `agent_core/cards/*`,
  `agent_core/providers/persist.py`, `agent_core/skills/pack.py`);
- live probes against the real API on `127.0.0.1:8000` (frontend confirmed running with
  `VITE_USE_MOCK=false`) — GETs only, plus exactly one sanctioned compile dry-run POST;
- SSR smoke-tests of all five routes on the dev server `127.0.0.1:8080` (all 200);
- JS-runtime checks for timestamp parsing (Node 22 / V8).

Labels: **VERIFIED** = confirmed against a live response or unambiguous code logic.
**SUSPECTED** = mechanism proven in code, runtime trigger not demonstrated (would need a
write or an out-of-band DB row). Severity: MAJOR / MINOR / TRIVIAL.

Totals: **13 MAJOR, ~40 MINOR/TRIVIAL, plus 3 live-state discoveries.**

---

## 1. Fleet index — `/agent-studio`

| # | Sev | Status | Finding |
|---|-----|--------|---------|
| 1.1 | MINOR | VERIFIED | Archive/restore never refreshes "Recent changes". `useArchiveAgentCard` invalidates `["agent-studio"]` (`api/agent-studio.ts:200`) but the change-log query lives under `["agent-change-log", …]` (`:903`) — no prefix match, so the log that just recorded the archive stays stale up to `staleTime` 30 s / window refocus. |
| 1.2 | MINOR | VERIFIED | Archive confirmation uses `window.confirm` (`agent-studio.index.tsx:257`). The codebase itself bans this pattern ("browser chrome titled localhost:8080 says", blocks renderer) in `prompt-studio.lazy.tsx:736-752`; the app even ships the themed replacement (`AlertDialog`). Inconsistent + ugly. |
| 1.3 | INFO | VERIFIED | Archived test leftovers ship in the DB and render under "Show archived": `e2e-audit-card-8216c4`, `qa-probe-clone-fd7ebd` (plus junk clones `sweep-probe-001-f562be`, `webchatbot`, `collectionsbot-v2-4` on the default list). Data hygiene, not code. |

Checked fine: eval reports arrive newest-first (live `createdAt DESC`) so `EvalTrend`'s
`slice(0,3).reverse()` is correct; reachability chips match live values including
`archived`; templates/cards/change-log response shapes match their TS types field-for-field;
archived filtering is server-side and correct (default 9 rows vs 11 with
`includeArchived=true`; garbage param → strict 422, frontend never sends one).

## 2. Card editor shell — `/agent-studio/$botId`

| # | Sev | Status | Finding |
|---|-----|--------|---------|
| 2.1 | MAJOR | SUSPECTED (every link code/live-verified) | Autosave can never converge on a bot seeded from defaults → permanent "unsaved" chip and a self-sustaining PATCH loop. `fingerprint()` is raw `JSON.stringify` (key-order sensitive) over local state; seed `DEFAULT_VOICE` omits `style`/`params`, while the backend always emits them in Pydantic field order (`db._prompt_voice`; confirmed in live JSON). First save stores a server-shaped baseline while local state keeps seed shape → `unsaved` recomputes true after every "Draft saved"; each save invalidates → refetch → new object identities re-run the effect. Dormant today only because all four first-party bots hydrate from server-shaped rows. `PublishDialog` already has `stableStringify` for its own diff — the editor fingerprint needs the same treatment. |
| 2.2 | MAJOR | VERIFIED | API failure renders as absence. `fetchPublishedPromptVersion` and `fetchActiveBotDeployment` end in `catch { return null }` (`api/prompt-studio.ts:166-171, 860-866`): during an outage a card that IS live shows "never published" and loses its rollback panel. The backend distinguishes real absence (404 `published_prompt_not_found` / `active_deployment_not_found`) from failure — the client throws that away. Textbook graceful-degradation lie. |
| 2.3 | MINOR | VERIFIED | Dead link renders an editable studio: `/agent-studio/no-such-bot` — card GET 404 is ignored (only `versionsQuery.isError` checked, lazy.tsx:1153), versions endpoint returns `200 []`, empty-history branch seeds defaults, header shows "—", and typing autosaves against a nonexistent botId. |
| 2.4 | MINOR | VERIFIED | Autosave always sends `summary: "draft autosave"` (`ensureStudioDraft`), clobbering the "restored from vX" note written by restore-as-draft on the next keystroke. Publish notes survive only because the final publish POST carries its own summary (backend persists it). |
| 2.5 | MINOR | latent | publish()/loadDraft()/rollback() assign persona/voice/guardrails without `DEFAULT_*` fallbacks (the hydration path has them). All live rows carry fields today; a null would crash the tabs downstream. |
| 2.6 | BACKEND latent | VERIFIED | `POST /agent-studio/cards/{bot_id}/publish` publishes the FIRST draft among the newest 20 (`main.py:2032-2038`), ignoring any client-specified draft — contradicts the editor's draftId model. UI doesn't call it (grep-verified); API-only foot-gun. |

Also verified OK: compile dry-run contract matches TS `CompileReport` (extra
`mission_entries` harmlessly ignored; gates G0–G15 + G-OB1..9 all present); version rows
are complete camelCase (`createdAt` present, agentCard/persona/voice/guardrails non-null on
all 4 bots incl. clones); sandbox search params validated; SSR 200 on all routes.

### 2a. System Prompt tab (+ StudioHeader, DiffModal, PublishDialog, VersionHistory)

| # | Sev | Status | Finding |
|---|-----|--------|---------|
| 2a.1 | MAJOR | VERIFIED | PublishDialog stays **pre-confirmed** after a successful publish. State reset runs only inside Radix-initiated close; programmatic `setPublishOpen(false)` (lazy.tsx:844) skips it, so `confirmText==="PUBLISH"`, typed `localeConfirm`, and the old note persist. Next open in the same mounted page: Confirm enabled with zero typing, previous note silently reused via `onConfirm(note \|\| …)`. Defeats the typed-confirmation gate entirely. (`PublishDialog.tsx:74-76,126-134,263`.) |
| 2a.2 | MINOR | VERIFIED | `unknown_variable` lint findings render once per occurrence — the panel's own dedupe invariant covers only CRM/flow codes (`PromptEditor.tsx:72-77` vs `prompt_lint.py:109-116` which emits per-hit). Latent on kaia (current tokens all known). |
| 2a.3 | MINOR | VERIFIED | PublishDialog change-summary ignores what publish actually sends for card-less bots: trafficPct/shadow/autoRollback live in `legacyShip` and appear nowhere in the diff → "Nothing differs from what is live" while shipping a materially different rollout. Authored cards are covered via `card.experiment`. |
| 2a.4 | MINOR | SUSPECTED | Discarding the last draft of a draft-only card reloads discarded content into the editor: fallback `published = history[0]` can BE the just-discarded row before refetch lands (lazy.tsx:774-803). |
| 2a.5 | MINOR | VERIFIED | `runCompile` ends `.catch(() => setCompileReport(null))` — no toast/marker; dialog silently loses gate evidence (contained by server-side publish gates). |
| 2a.6 | MINOR | VERIFIED | Typed-confirm normalization inconsistent: `PUBLISH` exact-match case-sensitive-untrimmed vs `LANGUAGE` trimmed+uppercased — trailing space defeats one gate but not the other. |
| 2a.7 | MINOR | VERIFIED | Draft-count dot is `<span aria-label>` with no role — not reliably announced, color-only signal (StudioHeader.tsx:101-106). |
| 2a.8 | MINOR | VERIFIED | Auto-lint + token estimate fire pre-hydration on empty prompt (transient misleading finding) and neither sets `retry:false`, so deterministic 400/422 retried 3×. |
| 2a.9 | MINOR | VERIFIED | Persona preview blob URL revoked only in stop/unmount paths, not `onended` (PersonaSliders.tsx:126-135). |

Checked fine: preset badge is derived (prompt+traits match) not stored; Undo restores both
halves; preset apply confirms in-app before overwriting authored text; diff baselines use
the actually-published row (no self-diff); versions newest-first matches `drafts[0]`/
resumable logic; attempt-suffix numbering correct on the live 4×"v1.5" cluster; dates parse,
future timestamps floored; div-by-zero guarded; CRM-token banner fires by design on the live
published prompt.

### 2b. Flow tab

| # | Sev | Status | Finding |
|---|-----|--------|---------|
| 2b.1 | MAJOR | masking VERIFIED, state SUSPECTED | Edge-only corrupt graph (`nodes:[], edges>0`) is classified "empty" everywhere: `isEmptyGraph` keys on nodes only (`api/flow.ts:151-153`) → canvas skips validation, parent forces `flowValid=true`, UI renders "No authored flow"; backend mirrors it (`flow_graph.py:400-401` short-circuits `assert_publishable` before dangling-edge checks :561-574). Probe proved the validator WOULD flag it (`dangling_target` on e-1). Published kaia v1_4 stores the `{nodes:[],edges:[]}` sentinel — indistinguishable from a corrupted edge-only row. Not producible through the UI today (node deletion removes touching edges). |
| 2b.2 | MINOR | SUSPECTED | Read path is all-or-nothing: one structurally broken `flow` jsonb (unknown key/wrong enum under `extra="forbid"`) raises ResponseValidationError → GET `/prompt-versions` 500s for the WHOLE bot → studio dead-ends. Merely-incomplete legacy rows are safe (pydantic defaults fill). Needs out-of-band write to demo. |
| 2b.3 | MINOR | VERIFIED | Duplicate node keys (drafts savable with `duplicate_node_key`) make ghost-edge resolution last-wins mid-edit (`FlowCanvas.tsx:524`) — tool hops draw into the wrong node; same ambiguity feeds `redundant_with_tool`. |
| 2b.4 | MINOR | VERIFIED | Client publish gate starts open (`flowValid=true`) and keeps the last result if `/flow/validate` dies — stale-ok window; server re-validation makes worst case a late 422, not breakage. |
| 2b.5 | MINOR | VERIFIED | Version-history DiffModal compares `{label,prompt,persona,voice,guardrails}` only — flow and agentCard omitted though versions store both (publish dialog includes them). Graph regressions invisible in compare. |
| 2b.6 | LIVE | VERIFIED | kaia's open draft v1_5-aace95 is materialised from an older script: 12 nodes vs today's 14 built-in (missing `confirm_identity`, `third_party`) and EVERY node has `entryFor=[]` → outbound missions have no door in the graph; Outbound tab will flag mismatches. Mitigation exists: "Reload built-in script…". |

Checked fine: validate-issue contract `{severity,code,message,nodeId,edgeId|null}` matches
end-to-end (3 dry-run probes incl. deliberately broken graph → 6 correctly-targeted issues);
drag commits only `position` (xyflow internals never leak into saved JSON); deletion composes
node+edges atomically; implicit edges undeletable; layout handles single-node/cycles; the old
twice-a-second validate loop is genuinely fixed (ref-based callback, `[graph]` deps);
autosave omits null flow (no wipe-before-load).

### 2c. Agent graph tab

Clean. Live `/agent-studio/cards/{id}/graph` matches `AgentGraph` exactly; handoff editor
spreads existing rows (`payload_schema` survives); reachability vocabulary matches ROUTE_TONE/
ROUTE_HELP; kaia's card handoffs agree with server edges.

### 2d. Persona tab

Covered under 2a.9 (blob URL). Preset application/confirmation/undo verified correct.

### 2e. Voice (TTS) tab

| # | Sev | Status | Finding |
|---|-----|--------|---------|
| 2e.1 | MINOR→confirmed LIVE | VERIFIED | Locale dropdown renders duplicate entries with duplicate React keys: `otherLocales` (page items, excluding only exact preset strings) overlaps `localeOptions` (locale-counts). Confirmed live on page one: `af-ZA, am-ET, ar, ar-AE` each appear twice (`VoiceCatalogBrowser.tsx:314-322, 338-348, 454-464`). Presets use prefix strings (`ta-`) but exclusion tests whole values (`ta-IN`) so nothing is ever excluded. |
| 2e.2 | MINOR (dormant) | VERIFIED | GA-status + hide-premium defaults can zero the catalog with no attribution ("No voices match these filters."), and compact mode renders NO status control while still forcing GA. Verified NOT triggerable today: every Indian locale probed (`hi-IN ta-IN bn-IN mr-IN te-IN gu-IN kn-IN ml-IN pa-IN or-IN`) has GA free voices equal to its total. |
| 2e.3 | MINOR | VERIFIED | Visiting the Voice tab can mutate a legacy draft: style-normalization effect writes `style: styles[0]` when stored style is null/stale → dirty → autosaved, zero operator action (`VoicePanel.tsx:519-524`). |
| 2e.4 | MINOR | VERIFIED | Enum param chip displays `options[0]` when stored value left the schema, but `effectiveParams` still sends the dead key — UI and wire diverge (schema-drift triggered). |
| 2e.5 | MINOR | VERIFIED | Preview/Stop disabled while synthesis in flight — uncancellable up to the 60 s blob timeout. |
| 2e.6 | MINOR | VERIFIED | `looksLikeShortName` regex misses `{provider}:{ref}` ids → legacy row with empty azureVoiceName silently resolves to hardcoded `en-IN-AartiNeural`. |
| 2e.7 | MINOR | VERIFIED | Catalog Refresh invalidates only catalog/sync keys — provider/locale counts (`staleTime` 60 s) and detail caches lag behind the "Catalog refreshed" toast. |
| 2e.8 | downgraded | VERIFIED | `min={spec.min ?? 0}` clamping: harmless today — every seeded schema declares min (fish volume −20…20, azure pitch ±50, s2.1 speed 0.5…2). Latent only. |

Note (accepted risk, flagged): deleting a tenant-default binding is one unconfirmed click.

### 2f. Guardrails tab

Clean — audited directly (no analyst covered it): honest loading/error/empty states on the
PII section ("Could not load redaction rules — this list is not a statement about what is
redacted"), read-only cross-link to Redaction Hub, six toggles map exactly onto the guardrail
booleans, sliders bounded. Trivia: word input lacks aria-label; duplicate chips possible only
via hand-edited data (addWord lowercases+duplicates-checks).

### 2g. Tools tab

| # | Sev | Status | Finding |
|---|-----|--------|---------|
| 2g.1 | MINOR | VERIFIED | `preview.data?.voice_tool_cap \|\| (card.tools?.max_voice_tools ?? 12)` swallows a legitimate server-reported cap of 0 (`AgentCardPanels.tsx:78`) — should be `??`. Latent (live cap 12). |
| 2g.2 | MINOR | VERIFIED-consistent-today | "on the card" counter uses `card.tools.locked` while row state also treats catalog-level locked tools as on — diverges only if they drift apart. |

### 2h. Skills tab (editor)

| # | Sev | Status | Finding |
|---|-----|--------|---------|
| 2h.1 | MINOR (downgraded from MAJOR) | VERIFIED | Attach writes `{skill_id: slug, version: "1"}` with no `pin` — but `schema.py:106-107` defaults `pin:"exact", version:"1"`, identical to every served row today. Becomes real the day any skill bumps past v1 (hardcoded "1" pins stale forever). |
| 2h.2 | MINOR | VERIFIED | Query error renders lying zero-counters (0 tok / 0 tok / 0 files) and asserts "Skill catalog is empty…" — false system statement instead of error (ToolsTab gets this right at :166-170). |
| 2h.3 | MINOR | VERIFIED | Token tile sums `description.length/4` only while labelled "Names + descriptions only", and duplicates `CompileReport.skill_description_tokens` which ToolsTab already fetches. |

### 2i. Connectors tab

| # | Sev | Status | Finding |
|---|-----|--------|---------|
| 2i.1 | MAJOR | VERIFIED | No `isPending/isError` branch: a failed connectors query renders as business advice — "No approved connectors… Approve connectors on Integrations" — while the live API returns two approved (`conn-lms`, `conn-paylink`). Sends authors chasing a nonexistent problem. (`AgentCardPanels.tsx:800,857-873`.) |
| 2i.2 | MINOR | VERIFIED | Bind snapshots `allowPrefixes` into the card; later catalog changes never propagate and the warning banner shows the stale list (possibly by design; no staleness signal). |

### 2j. Policy tab

MINOR·VERIFIED — binding lozenge tone hardcoded success regardless of value
(`bindings[engine.key] || "required"`); coverage itself correct (six keys match
REQUIRED_POLICY_KEYS; live bindings carry exactly those).

### 2k. Evals tab

| # | Sev | Status | Finding |
|---|-----|--------|---------|
| 2k.1 | MINOR | VERIFIED(logic)/SUSPECTED(vocab) | Any non-"pass" report status renders red danger (:328-330, :466) — `skipped` shown as failed, contradicting the tab's own copy ("Skipped is honest"). All 46 live reports happen to be `pass`. |
| 2k.2 | MINOR | VERIFIED(live) | Scheduled lapse-suite reports are filed with `botId:null` (verified across the live corpus) → insurance-v1's scoped Evals tab says "never run" while those suites run green daily. |
| 2k.3 | MINOR | SUSPECTED | Displayed requirement defaults (`card.eval?.require ?? ["regression","redteam"]`) are rendered-checked but never stored until touched — UI shows requirements the card doesn't have. |

### 2l. Outbound tab

| # | Sev | Status | Finding |
|---|-----|--------|---------|
| 2l.1 | MINOR | VERIFIED | G12 inline warning skips 0%: warns only for `>0 && <100` while the backend fails 0 too (`canary_zero`). Slider min=0 invites it. |
| 2l.2 | MINOR | VERIFIED | Compile-preview-as-query fires a POST per keystroke (no debounce on `useCompilePreview`, keyed by serialized card). |
| 2l.3 | MINOR | VERIFIED | CohortBuilder numeric inputs unbounded: negatives pass through; `num(limit) ?? 500` honors 0 (`??` misses it). Preview errors ARE surfaced, bounding impact. |
| 2l.4 | MINOR | SUSPECTED | Campaign Start enabled for cancelled runs (guard is `status === "finished"` only); restart-from-cancelled legality unverified backend-side. |

❌ Ruled out during verification: "OutboundGates stuck on checking… for inbound cards" —
REFUTED. `_outbound_gates` always appends at least G-OB1 as `skipped` for inbound/no-card
(`compile.py:264,268`, call site :908), so both UI branches are reachable and the limbo
state cannot persist beyond loading.
Coverage caveat: `OutboundCardEditor.tsx` sub-editors (DirectionPanel/MissionsEditor/
CadencesEditor/PostCallEditor) and NumberPoolTable internals were not read this pass.

### 2m. Ship tab

| # | Sev | Status | Finding |
|---|-----|--------|---------|
| 2m.1 | MINOR | VERIFIED | Canary rollback success toast can lie: always "Canary rolled back to baseline", but `canary.py:151-161` only swaps when a baseline exists — otherwise status flips to `rolled_back` with nothing reactivated. |
| 2m.2 | MINOR | VERIFIED | Shadow + 100% accepted silently: contradictory config compiles green (G12 passes 100% regardless; canary routing sends pct≥100 straight through). |
| 2m.3 | MINOR | SUSPECTED | Prior-deployment fallback picks the first `retired\|rolled_back` row with no ordering guarantee (lazy.tsx:300). Dormant: kaia has exactly one prod deployment with `rollbackDeploymentId:null` and the honest "no prior" toast works. |
| 2m.4 | MINOR | SUSPECTED | Card-less bots' ship settings live in unpersisted `legacyShip` — controls reset to defaults on reload while a shipped experiment may differ. All four seeded bots are authored, so dormant. |
| 2m.5 | TRIVIAL | VERIFIED | `{warning.length} warning` → "2 warning". |

Verified fine: rollback-trigger vocabulary agrees four ways (UI set = TS set = schema Literal
= conditions sweep_rollbacks evaluates); ShipTab's G12 pre-warning mirrors backend semantics
exactly; experiments wire shape camelCase-complete.

### 2n. Change log tab

| # | Sev | Status | Finding |
|---|-----|--------|---------|
| 2n.1 | MAJOR | VERIFIED | `warn` gates rendered as "gates failed": filter is `v!=="pass" && v!=="skipped"` (:104) and prints red "gates failed: …" (:138-141) — but `GateStatus` includes `"warn"` and G10 legitimately emits it (`compile.py:45,845`). A warned publish is displayed as FAILED on the tamper-evidence screen — precisely the wrong-verdict class this tab exists to prevent. |
| 2n.2 | MINOR | VERIFIED | `agent.restore` entries have no verb/tone mapping (:30-40) — raw string rendered, though the backend records restores (`db.py:13291 record_restore`). |

Verified fine (live): filtered `?botId=` request returned entries=0 with `chain.checked=5`
tenant-wide and the UI draws exactly that distinction; broken-chain / checked=0 / request-
error states all degrade loudly; space-separated timestamps normalized before parsing;
rollout/gates/versionLabel arrows match live JSON.

## 3. Skills library — `/agent-studio/skills`

| # | Sev | Status | Finding |
|---|-----|--------|---------|
| 3.1 | MAJOR | VERIFIED (re-confirmed live in this session) | Signed first-party bodies stored as MOJIBAKE, permanently. `verify-and-disclose` body contains U+00E2 U+0080 U+0094 (raw UTF-8 em-dash bytes mis-decoded) where `packs/verify-and-disclose/SKILL.md:29` has "—" (codepoints measured; `body.Contains(U+2014)=False`). Disk loader reads UTF-8 correctly (`pack.py:159`), so rows came from an older wrong-encoding seed; `list_skills` reseeds only when the catalog is EMPTY (`persist.py:166-172`) → corruption persists forever. contentHash/signature were computed over the corrupt bytes: everything renders green. Editor + Preview show the garbage (`$skillId.tsx:48,220-228`). ptp-negotiate probed clean (no em-dashes at all). |
| 3.2 | MINOR | VERIFIED (live) | Export filename unreadable cross-origin: `_CORS_EXPOSE_HEADERS` omits Content-Disposition (`main.py:577-583`; live expose-header list confirms) → `headers.get("Content-Disposition")` null in `apiGetBlob` → fallback `${skill.id}.zip` always wins despite the server sending the correct quoted filename. `main.py:570-576` documents this exact bug class for TTS headers; export repeats it. |
| 3.3 | MINOR | VERIFIED | Gardener drafts carry literal string `"None"` as eval_suite (gardener.py None → f-string dump → re-parsed as string). Baked into contentHash and exported markdown; UI ignores the field today. |
| 3.4 | MINOR | VERIFIED | Index isError ternary swaps away last-good cached grid (`index.tsx:227-231`). |
| 3.5 | MINOR | VERIFIED (live) | "Attached:" text cites archived cards (`e2e-audit-card-8216c4` — archivedAt 2026-08-19) because attachment counting ignores archive state (`persist.py:114-121`). |

Checked fine: id-or-slug resolution identical live (both forms probed); `/skills/scripts`
declared before `/{skill_id}`; SkillSummary fields all present camelCase, arrays never null;
versions[] ↔ latestVersionId consistent (Restore gated to signed non-latest, backend
enforces signed+valid-HMAC revert); signature vocabulary exhaustive signed/unsigned; body
always populated so ignoring `markdown` can't blank the editor; token math equals backend
approx; mutation payloads match schemas (409 detail strings surface honestly); import
accept-set matches branches; server auto-seeds an empty catalog; no search/filter drops rows.

## 4. Skill detail — `/agent-studio/skills/$skillId`

| # | Sev | Status | Finding |
|---|-----|--------|---------|
| 4.1 | MAJOR | VERIFIED (code) | Signing never updates the page: `useSignSkill` invalidates `["agent-studio","skills"]` (`api/agent-studio.ts:641`) which does not prefix-match the detail key `["agent-studio","skill",skillId]` (`:595`); the fresh row the sign endpoint returns is discarded (`$skillId.tsx:156`). After the "Signed" toast the lozenge still reads unsigned, Sign stays enabled, Revert stays disabled until an unrelated refetch. Contrast: useRevertSkill/usePatchSkill invalidate `["agent-studio"]` correctly. |
| 4.2 | MAJOR | VERIFIED (code) | No `isError` branch: any 500/network failure renders "Skill not found." (`$skillId.tsx:85-100`). Compounded by RQ v5 defaults retrying 404s 3× (1s/2s/4s) ≈ 7 s of spinner for a genuinely bad URL. Index page handles errors honestly by contrast. |
| 4.3 | MINOR | VERIFIED | Script runner claims "must be a JSON object" but only try/catches JSON.parse: `[1,2]` passes the unchecked cast; backend coerces non-dict to `{}` (`main.py:2247`) and runs anyway, rendering `numeric_required` as if user input was evaluated. |
| 4.4 | MINOR | VERIFIED | Sign button `.then(toast)` with no `.catch` (unlike Revert/Run) — failed sign is a silent unhandled rejection. |
| 4.5 | MINOR | SUSPECTED | description/body/selected/scriptName useState never resets on skillId change; component stays mounted across param navigation → B opens with A's dirty text (reachable via history traversal today). |
| 4.6 | MINOR | cosmetic | Tab title uses raw URL param while header resolves slug. |
| 4.7 | MINOR | SUSPECTED | "Load in sandbox" hardcodes `botId:"kaia-v2-4"` regardless of the skill's real attached cards. |

---

## Cross-cutting themes

1. **Graceful degradation lies (the repo's documented #1 failure mode) recur in new code:**
   ConnectorsTab renders error as business advice; Skill detail renders failure as "not
   found"; `fetchPublishedPromptVersion`/`fetchActiveBotDeployment` flatten failures to null;
   SkillsTab renders zero-counter tiles + a false "catalog is empty" claim; ShipTab's
   rollback toast claims success when nothing swapped; bindings render dead vendors green;
   ChangeLogTab upgrades warns to failures.
2. **React-query invalidation keys that don't prefix-match:** sign (["agent-studio","skills"]
   vs ["agent-studio","skill"]) and archive/publish never touching ["agent-change-log"].
3. **Key-order-sensitive JSON fingerprints:** the autosave loop risk (editor) sits next to
   PublishDialog's `stableStringify` — the fix pattern already exists in-file.
4. **Silent-fallback class:** hardcoded kaia-v2-4 in skill sandbox button; hardcoded
   en-IN-AartiNeural voice fallback; unordered prior-deployment fallback; stale modelId kept
   across slot switches.

## Live-state discoveries (fix data/skill drift and tabs change color)

- **kaia-v2-4's open draft is unpublishable right now**: compile dry-run fails **G9
  signed_skills** — skills allow `set_contact_preference` (verify-and-disclose) and
  `capture_nonpayment_reason` (ptp-negotiate, hardship-intake) but the draft card's
  `tools.include ∪ locked` lacks them. The published card (23 include tools) passes:
  "8 signed skill(s)". Whether the draft narrowed tools or packs grew is the next question
  for whoever owns the card.
- **Mojibake inside a production-signed pack** (3.1) — hash/signature cover corrupt bytes.
- **Lapse suites filed botId:null** (2k.2) — scheduler attribution gap.

## Suggested fix order (impact ÷ effort)

1. 4.1 + 1.1 — two one-line invalidation-key fixes.
2. 2a.1 — reset PublishDialog state on successful publish (move reset out of onOpenChange).
3. 2.2 — stop catching-all to null; distinguish 404 from failure in the two fetchers.
4. 2n.1 + 2k.1 — gate/status vocab: treat `warn` as warn, `skipped` as skipped.
5. 3.1 — one-off repair migration: re-read first-party packs from disk and re-sign.
6. 2i.1 / 4.2 — add isPending/isError branches (pattern exists elsewhere in-repo).
7. 2e.1 — exclude by prefix-match or build the dropdown solely from counts.
8. 2.1 — switch editor fingerprint to stableStringify.
