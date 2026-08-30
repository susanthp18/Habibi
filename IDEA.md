# BigBound AI — Collections Intelligence Platform

## What this is, in one line

A regulated Indian BFSI collections operation, run as software: it decides what
should happen to a delinquent borrower, when, through which channel, under whose
authority — and then executes it, with voice AI as one channel among several.

## What it is NOT

Not "an AI voice agent." The voice agent is the **mouth**. The P&L is everything
around the call: who gets contacted, how fast, on which channel, with what
authority, and whether a promise actually gets paid.

Never pitch, name, or design anything in this repo as a voice demo. The correct
framing: we run the same work a telecaller, floor lead, QA analyst, DND desk and
clerk do every day, then put voice AI on the high-volume early buckets so humans
only take hardship, disputes and settlements — and so every material decision
fires the same hour as the event.

## The buyer and the scoreboard

The buyer is a **collections head** at a bank, NBFC, fintech lender or insurer.
Not a voice-AI enthusiast. Their scoreboard, in priority order:

  - Cost to collect
  - Recovery / roll-forward into NPA
  - PTP **kept** % (promises without keep-rate are vanity)
  - Time-to-first-touch after bounce — hours, not days; this is the early-bucket P&L
  - % of 1–30 DPD book contacted in 48h — coverage is the lift, dialogue quality is secondary
  - Compliance coverage — 100% of calls scored; sampling is not monitoring
  - Cost per resolved contact

The profit lever is **delay, not dialogue**. A borrower who misses EMI on Day 1
and is contacted on Day 12 has already reclassified the debt.

## The governing thesis

> Don't predict who will repay. Predict who will repay **because of** our
> intervention.

τ(action, x) = P(cure | action) − P(cure | no action)

A response model ranks self-curers highest — borrowers who would have paid
anyway — so it spends the most expensive capacity on people who needed nothing
and books their payment as its own success. Everything in the decision engine
follows from rejecting that.

## Repository shape

Root: D:\Hackathon — two deliverables in one tree, one branch: greptile-review/local-wip

  backend/    Python 3.11 · FastAPI · PostgreSQL 16 + pgvector · SQLAlchemy ·
              Alembic · pytest. ~520 modules, 144 in agent_core/, 140 test files,
              98 migrations, 25 authoritative sql/ files, 20 operator scripts.
              Docker Compose services: db, redis, minio, api, worker, bot_worker,
              voice, voice_insurance.
              Voice runs on **Pipecat, on-prem** — not managed cloud voice.
              The deployment target is inside a bank; sort every technical
              recommendation by what survives in that environment.

  Habibi/     React 19 · TypeScript · Vite 8 · TanStack Router/Query/Start ·
              Tailwind 4 · Radix UI · Recharts · lucide-react.
              354 components, 41 routes, 41 API client modules.
              It is an **operator console** — scanned and operated, not read.
              House style is machine-enforced: scripts/check-spacing-scale.mjs
              and scripts/check-type-scale.mjs run inside `npm run lint`.

## The four design notes that govern the work

Read the relevant one BEFORE changing code in its area. They are authoritative;
where a doc and a comment disagree, verify against the code and fix the doc.

  decision-intelligence-engine.md  — WHETHER, WHAT and WHEN to act. The uplift
      reframing, the granularity ladder, off-policy evaluation, the promotion
      gate, the Action Contract (§12) and the open questions (§19).
      Implemented in backend/agent_core/treatment/ (24 modules).

  outbound-agent-engine.md — everything DOWNSTREAM of the decision: authoring
      the agent, placing the call, running the conversation, closing the loop.
      Its three objects: the mission, the attempt, the outcome.

  roadmap-features.md — the durable product plan. Start from the chore, the
      delay, and the decision that must fire the same hour as the event. Never
      start from "we need a better voice agent."

  multilingual-architecture.md — language handling across the stack.

## Current state (2026-08-22)

  - Backend suite: 1979 passed, 12 skipped, 0 failed (~7m34s). It is GREEN.
  - The outbound engine is LIVE: TREATMENT_MODE=live, CAMPAIGN_RUNTIME_ENABLED,
    OUTBOUND_EVAL_GATE_ENABLED, BOUNCE_VOICE_ENABLED all on.
  - The decision engine's full learning loop is built and demonstrated on a
    real 18,000-decision corpus: corpus generator, exploration with logged
    propensities, a genuine control arm, segment ladder with empirical-Bayes
    shrinkage, IPS/SNIPS/doubly-robust OPE, drift and calibration monitors,
    and a champion/challenger promotion gate that refuses by default.
  - Two items are held back deliberately, not left undone: cross-tenant
    hierarchical priors (blocked on a contractual/DPDP question, §19.1) and
    individual-level CATE (gated by the ladder's own promotion rule).
  - The working tree carries ~270 uncommitted files. This is expected.

## The characteristic failure mode of this codebase

**It degrades gracefully.** Damage almost never surfaces as an exception — it
surfaces as a plausible-looking number. A default that hides a missing input, an
except block that swallows, a fallback that makes a broken path look healthy, a
divide by a floored constant. Nine bugs found in the last work cycle were all
this same shape.

Consequences for how to work here:
  - Most new code should be REFUSAL machinery: gates that say no, checks that
    report "unavailable" with a reason rather than degrading to a wrong answer.
  - Never trust a green number without asking what it would look like if the
    input were missing.
  - Root-cause over patching, permanently. A workaround that makes a symptom
    disappear in a system that degrades gracefully is indistinguishable from a fix.

## Environment facts that cost real time when forgotten

  - Windows 11, PowerShell primary (no &&, no ternary, no head/tail/which);
    Git Bash available for POSIX. Host Python is .venv/Scripts/python.
  - Backend tests MUST run in the container WITH the dev overlay
    (docker-compose.dev.yml). Without it you test the image baked at build
    time, not your edits, and a green run means nothing.
  - NEVER run pytest or Alembic while the corpus simulator is running. They
    contend on Postgres locks; alembic upgrade takes ACCESS EXCLUSIVE and
    queues everything behind it. The resulting failures look like real bugs.
  - Tests share one Postgres transaction: one bad column name aborts it and
    cascades. Read the FIRST failure, never the count.
  - The db_tx fixture freezes now() at transaction start — back-date rows in
    tests, never wall-clock them.
  - Schema changes need BOTH an Alembic migration AND the matching sql/*.sql
    edit. sql/ is the authoritative fresh-install schema. Two commits already
    exist solely to repair that drift; do not create a third.
  - backend/.env holds LIVE Twilio credentials. Never print, echo, cat or log
    it. Presence, length and prefix only. Mask DSNs.
  - NEVER `git stash` in this repo. Never bulk-discard.

## What "good" looks like

Backend: a decision that can be defended to a bank's compliance committee — the
rule that fired, the version of the rule set in force at that instant, the
authority that permitted it, and the evidence it was worth doing. Every material
decision leaves a trace.

Frontend: an operator console where what needs attention reads at a glance
without reading any digits. Every data surface carries four states — loading,
empty, error, and degraded (reachable but stale or partial). A degraded state
must be VISIBLE; silently substituting fallback data for real data is the same
graceful-degradation failure, moved into the UI.
