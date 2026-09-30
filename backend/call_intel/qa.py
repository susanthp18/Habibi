"""The QA cascade: evidence, then small models, then the judge only where needed.

* **Tier 0, evidence.** The live scorer (``agent_core.live_qa.scorecard``)
  settles the compliance criteria at hangup from guardrail flags, disclosures,
  identity verification, promises and the calling window. Its ``[live]`` cells
  are final here too.
* **Tier 1, small models.** The signals stage says whether a criterion even
  had an opportunity (no hardship, no confusion, no negative turn: nothing to
  acknowledge) and how the customer's mood moved. Settled at confidence >=
  ``SETTLE``; everything else goes up.
* **Tier 2, the judge.** ``qa_autoscore.judge`` scores only the unsettled
  criteria, with tier 0 and 1's findings as context, on the masked transcript.
  A deterministic ``CALIBRATION_PCT`` sample goes to the judge in full, so how
  often tier 1 agrees with it is measured, not assumed.

Every cell records its tier, confidence, evidence (turn indexes) and the
model that decided it. When the judge is unavailable the unsettled cells stay
neutral with low confidence, which the QA queue shows as needing a person.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from sqlalchemy import text

from call_intel import models
from call_intel.inputs import Call

logger = logging.getLogger(__name__)

#: Tier 1 settles a criterion at or above this confidence.
SETTLE = 0.8
#: Share of calls whose soft criteria all go to the judge, for agreement stats.
CALIBRATION_PCT = 10
NEUTRAL = 3.0
#: The rubric's "within the first 20 seconds" for the recording notice.
RECORDING_NOTICE_BY_S = 20
JUDGE_VERSION = "azure-openai:analysis"


def in_calibration(interaction_id: str) -> bool:
    digest = hashlib.sha256(f"qa-calibration:{interaction_id}".encode()).digest()
    return int.from_bytes(digest[:4], "big") % 100 < CALIBRATION_PCT


def _signals(conn: Any, interaction_id: str) -> dict[str, Any]:
    rows = conn.execute(
        text("SELECT s.kind, s.label, s.score, t.turn_index FROM interaction_turn_signals s "
             "JOIN interaction_transcript t ON t.id = s.transcript_turn_id WHERE s.interaction_id = :ix "
             "ORDER BY t.turn_index"),
        {"ix": interaction_id},
    ).mappings().all()
    intents: dict[str, list[int]] = {}
    sentiment: list[tuple[int, float]] = []
    for r in rows:
        if r["kind"] == "intent":
            intents.setdefault(r["label"], []).append(int(r["turn_index"]))
        elif r["kind"] == "sentiment":
            sentiment.append((int(r["turn_index"]), float(r["score"])))
    return {"intents": intents, "sentiment": sentiment}


def tier1(cid: str, sig: dict[str, Any], facts: dict[str, Any]) -> tuple[float, float, list[int], str] | None:
    """(score, confidence, evidence turns, note) when the signals can say, else None."""
    intents, sentiment = sig["intents"], sig["sentiment"]
    negative = [t for t, s in sentiment if s <= -0.25]
    if cid == "emp-acknowledge":
        moments = sorted({*negative, *intents.get("hardship", []), *intents.get("confusion", [])})
        if not moments:
            return NEUTRAL, 0.9, [], "No distress or confusion to acknowledge"
        return None  # there was something to acknowledge: did the agent? The judge reads it.
    if cid == "emp-tone":
        if not negative and not facts["flags"] and sentiment:
            return 5.0, 0.85, [], "Customer stayed neutral or positive; no conduct flags"
        return None
    if cid == "ups-pitch":
        if not facts["upsell_presented"]:
            return NEUTRAL, 0.95, [], "No product pitched"
        return None
    if cid == "res-identify":
        # Asked for a person, a dispute or an opt-out and the call routed it:
        # the need was identified. Anything subtler is the judge's.
        routed = (intents.get("escalation") and facts["handoff"]) or (intents.get("opt_out") and facts["opted_out"])
        if routed:
            return 5.0, 0.85, sorted({*intents.get("escalation", []), *intents.get("opt_out", [])}), \
                "Customer's request was recognised and acted on"
        return None
    return None


def _facts(conn: Any, interaction_id: str) -> dict[str, Any]:
    row = conn.execute(
        text("SELECT upsell_presented, ptp_captured, source_payload -> 'languages' AS languages "
             "FROM interactions WHERE id = :ix"), {"ix": interaction_id}
    ).mappings().first() or {}
    languages = row.get("languages") if isinstance(row.get("languages"), dict) else {}
    flags = [r[0] for r in conn.execute(
        text("SELECT DISTINCT flag FROM interaction_flags WHERE interaction_id = :ix"), {"ix": interaction_id})]
    return {
        "flags": flags,
        "upsell_presented": bool(row.get("upsell_presented")),
        # The call's languages and the agent's replies in a script none of them
        # use (voice_studio.call_languages): evidence for any language criterion.
        "languages": [str(lang) for lang in languages.get("spoken") or []],
        "off_script": [str(o.get("script")) for o in languages.get("offScript") or [] if isinstance(o, dict)],
        "ptp": bool(row.get("ptp_captured")),
        "handoff": bool(conn.execute(text("SELECT 1 FROM interaction_handoffs WHERE interaction_id = :ix LIMIT 1"),
                                     {"ix": interaction_id}).first()),
        "opted_out": bool(conn.execute(text("SELECT 1 FROM bot_tool_calls WHERE interaction_id = :ix "
                                            "AND tool_name = 'record_opt_out' AND result_ok LIMIT 1"),
                                       {"ix": interaction_id}).first()),
        "verified": bool(conn.execute(text("SELECT 1 FROM identity_verifications WHERE interaction_id = :ix "
                                           "AND status = 'verified' LIMIT 1"), {"ix": interaction_id}).first()),
        # Seconds in when the agent gave the recording notice; -1 never; None not measured.
        "recording_notice": (lambda r: None if r is None else (r.read_at_sec if r.read else -1))(
            conn.execute(text("SELECT read, read_at_sec FROM interaction_disclosures WHERE interaction_id = :ix "
                              "AND label = 'Call recording notice' AND read_by_kind = 'bot' LIMIT 1"),
                         {"ix": interaction_id}).first()),
    }


def _evidence_text(sig: dict[str, Any], facts: dict[str, Any]) -> str:
    lines = [f"- Customer intents detected: " + (", ".join(
        f"{k} (turns {', '.join(map(str, v))})" for k, v in sig["intents"].items()) or "none")]
    if sig["sentiment"]:
        first, last = sig["sentiment"][0][1], sig["sentiment"][-1][1]
        lines.append(f"- Customer sentiment: {first:+.2f} at the start, {last:+.2f} at the end "
                     f"(-1 very negative, +1 very positive)")
    lines.append(f"- Identity verified: {'yes' if facts['verified'] else 'no'}")
    lines.append(f"- Promise to pay captured: {'yes' if facts['ptp'] else 'no'}")
    lines.append(f"- Handed to a person: {'yes' if facts['handoff'] else 'no'}")
    lines.append(f"- Guardrail flags: {', '.join(facts['flags']) or 'none'}")
    if facts.get("languages"):
        lines.append(f"- Languages the customer spoke: {', '.join(facts['languages'])}")
    if facts.get("off_script"):
        lines.append(f"- Agent replies written in a script none of those languages use: {len(facts['off_script'])} "
                     f"({', '.join(sorted(set(facts['off_script'])))})")
    return "\n".join(lines)


def run_qa(call: Call) -> dict[str, str]:
    import db
    import qa_autoscore
    from agent_core.live_qa.scorecard import is_live_locked, score_completed_interaction

    score_completed_interaction(call.interaction_id)  # tier 0; no-op when the card exists
    with db.engine.connect() as conn:
        card = conn.execute(
            text("SELECT id, rubric_id, status FROM qa_scorecards WHERE interaction_id = :ix"),
            {"ix": call.interaction_id},
        ).mappings().first()
        if card is None or card["status"] == "final":
            return {"qa": "skipped"}  # nothing to score, or a person already has
        rubric = db.load_rubric_tree(card["rubric_id"])
        entries = {r["criterion_id"]: r for r in conn.execute(
            text("SELECT criterion_id, final_score, note, tier FROM qa_scorecard_entries WHERE scorecard_id = :id"),
            {"id": card["id"]},
        ).mappings()}
        sig, facts = _signals(conn, call.interaction_id), _facts(conn, call.interaction_id)

    criteria = [c for s in (rubric or {}).get("sections", []) for c in s.get("criteria", [])]
    calibrating = in_calibration(call.interaction_id)
    decided: dict[str, dict[str, Any]] = {}
    unsettled: list[dict[str, Any]] = []
    for c in criteria:
        cid = c["id"]
        # Rules name the criterion by lineage: a rubric edit gives it a new id
        # (db_qa.create_rubric_version) but it is still the same question.
        rule = c.get("lineageId") or cid
        entry = entries.get(cid) or {}
        if entry.get("tier") == "human":
            continue
        if rule == "cmp-recording" and call.channel == "voice" and facts["recording_notice"] is not None:
            # Measured from what the agent said (signals stage), not inferred
            # from the absence of a live flag: the live check only flags when
            # the agent's guardrails demand the notice.
            at = facts["recording_notice"]
            score, note = ((5.0, f"Recording notice given at {at}s") if 0 <= at <= RECORDING_NOTICE_BY_S
                           else (3.0, f"Recording notice given late, at {at}s") if at >= 0
                           else (0.0, "Recording notice never given"))
            if is_live_locked(entry.get("note")) and float(entry["final_score"] or 0) < score:
                score, note = float(entry["final_score"] or 0), entry["note"]  # a live failure stands
            decided[cid] = {"tier": "evidence", "confidence": 1.0, "score": score, "note": note,
                            "evidence": {"disclosureAtSec": at if at >= 0 else None}, "model": "rules"}
            continue
        if is_live_locked(entry.get("note")):
            decided[cid] = {"tier": "evidence", "confidence": 1.0, "score": float(entry["final_score"] or 0),
                            "note": entry["note"], "evidence": {"flags": facts["flags"]}, "model": "rules"}
            continue
        guess = tier1(rule, sig, facts)
        if guess and guess[1] >= SETTLE and not calibrating:
            score, conf, turns, note = guess
            decided[cid] = {"tier": "model", "confidence": conf, "score": score, "note": note,
                            "evidence": {"turns": turns}, "model": models.version(models.NLI)}
        else:
            unsettled.append({**c, "_tier1": guess})

    judged = qa_autoscore.judge(call.interaction_id, [{k: v for k, v in c.items() if k != "_tier1"}
                                                     for c in unsettled], _evidence_text(sig, facts)) \
        if unsettled else {}
    for c in unsettled:
        cid, guess = c["id"], c["_tier1"]
        if judged and cid in judged:
            score, note = judged[cid]
            decided[cid] = {"tier": "llm", "confidence": 0.9, "score": score, "note": note,
                            "evidence": {"tier1": list(guess[:2]) if guess else None}, "model": JUDGE_VERSION}
        elif guess:
            score, conf, turns, note = guess
            decided[cid] = {"tier": "model", "confidence": conf, "score": score, "note": note,
                            "evidence": {"turns": turns}, "model": models.version(models.NLI)}
        else:
            # Nobody could decide: neutral, and low confidence puts it in front of a person.
            decided[cid] = {"tier": "model", "confidence": 0.3, "score": NEUTRAL,
                            "note": "Needs a reviewer: the automated judge was unavailable",
                            "evidence": {}, "model": None}

    db.patch_scorecard(card["id"], {"entries": [
        {"criterionId": cid, "aiSuggested": d["score"], "score": d["score"], "note": d["note"]}
        for cid, d in decided.items()
    ]})
    with db.engine.begin() as conn:
        for cid, d in decided.items():
            conn.execute(
                text("UPDATE qa_scorecard_entries SET tier = :tier, confidence = :conf, evidence = CAST(:ev AS jsonb), "
                     "model_version = :mv WHERE scorecard_id = :sc AND criterion_id = :cid"),
                {"tier": d["tier"], "conf": d["confidence"], "ev": json.dumps(d["evidence"]),
                 "mv": d["model"], "sc": card["id"], "cid": cid},
            )
    tiers = {t: sum(1 for d in decided.values() if d["tier"] == t) for t in ("evidence", "model", "llm")}
    logger.info("call_intel %s: QA %s (judge %s)%s", call.interaction_id, tiers,
                "ok" if judged is not None else "unavailable", " [calibration]" if calibrating else "")
    return {"qa": f"evidence:{tiers['evidence']} model:{tiers['model']} llm:{tiers['llm']}"}
