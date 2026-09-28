"""Per-turn conversation signals: customer sentiment, customer intents, disclosures.

Measured on our own calls before being trusted (call_intel.eval):

* Sentiment (multilingual distilbert) separates angry from pleased reliably in
  English and Hindi; it only runs on the customer's turns.
* Zero-shot NLI (mDeBERTa, ~30 ms a pair on 2 CPUs) is reliable for a few
  clearly-worded customer intents -- asking for a person, asking not to be
  called, disputing the debt, having lost a job -- and was NOT reliable for
  judging the agent (threats, empathy scored ~0.2 either way). Agent behaviour
  is therefore left to evidence (guardrail flags) and the QA judge, not here.

Each label has its own threshold; a turn can carry several intents.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text

from call_intel import models
from call_intel.inputs import Call

logger = logging.getLogger(__name__)

#: intent -> (hypotheses, threshold on the best hypothesis' P(entailment)).
#: The ids are the transcript intent vocabulary Bot analytics already groups by.
INTENTS: dict[str, tuple[tuple[str, ...], float]] = {
    "escalation": (("The speaker asks to talk to a human.",), 0.5),
    "opt_out": (("The speaker asks not to be called again.",), 0.5),
    "dispute": (("The speaker says they do not owe this money.",), 0.4),
    "hardship": (("The speaker lost their job.", "The speaker has no money."), 0.35),
    "confusion": (("The speaker did not understand.",), 0.2),
}
#: Sentiment below this is a negative turn, above POSITIVE a positive one.
NEGATIVE, POSITIVE = -0.25, 0.25


def _label(score: float) -> str:
    return "negative" if score <= NEGATIVE else "positive" if score >= POSITIVE else "neutral"


def detect(call: Call) -> dict[str, Any]:
    """{sentiment: {turn: score}, intents: {turn: [(intent, p)]}} for the customer's turns."""
    customer = [t for t in call.turns if t.speaker == "customer" and len(t.text.split()) >= 2]
    scores = models.sentiment([t.text for t in customer])
    pairs, index = [], []
    for t in customer:
        for intent, (hypotheses, _) in INTENTS.items():
            for h in hypotheses:
                pairs.append((t.text, h))
                index.append((t.index, intent))
    probs = models.entailment_raw(pairs)
    best: dict[tuple[int, str], float] = {}
    for key, p in zip(index, probs):
        best[key] = max(best.get(key, 0.0), p)
    intents: dict[int, list[tuple[str, float]]] = {}
    for (turn, intent), p in best.items():
        if p >= INTENTS[intent][1]:
            intents.setdefault(turn, []).append((intent, round(p, 3)))
    return {
        "sentiment": {t.index: round(s, 3) for t, s in zip(customer, scores)},
        "intents": {k: sorted(v, key=lambda x: -x[1]) for k, v in intents.items()},
    }


_INTENT_WORDS = {
    "escalation": "asked for a person", "opt_out": "asked not to be called again",
    "dispute": "disputed the amount", "hardship": "described financial hardship",
    "confusion": "was confused at points",
}


def call_summary(conn: Any, call: Call, found: dict[str, Any]) -> str:
    """What happened on the call, from its recorded outcomes -- not a model's
    paraphrase: every clause is a row the call wrote (verification, promise,
    callback, dispute, handoff, opt-out) or a measured signal."""
    from agent_core.clock import to_local
    from money_inr import inr

    ix = call.interaction_id
    one = lambda sql: conn.execute(text(sql), {"ix": ix}).mappings().first()  # noqa: E731
    parts: list[str] = []
    verified = one("SELECT 1 AS ok FROM identity_verifications WHERE interaction_id = :ix AND status = 'verified' LIMIT 1")
    parts.append("Identity verified." if verified else "Identity not verified.")
    promise = one("SELECT amount, promised_at FROM promises WHERE interaction_id = :ix ORDER BY created_at DESC LIMIT 1")
    if promise:
        parts.append(f"Promised {inr(float(promise['amount']))} by {to_local(promise['promised_at']):%d %b %Y}.")
    callback = one("SELECT scheduled_at FROM callbacks WHERE interaction_id = :ix ORDER BY scheduled_at DESC LIMIT 1")
    if callback and callback["scheduled_at"]:
        parts.append(f"Callback booked for {to_local(callback['scheduled_at']):%d %b %Y %H:%M}.")
    if one("SELECT 1 AS ok FROM disputes WHERE interaction_id = :ix LIMIT 1"):
        parts.append("Dispute raised.")
    if one("SELECT 1 AS ok FROM interaction_handoffs WHERE interaction_id = :ix LIMIT 1"):
        parts.append("Handed to a person.")
    if one("SELECT 1 AS ok FROM bot_tool_calls WHERE interaction_id = :ix AND tool_name = 'record_opt_out' "
           "AND result_ok LIMIT 1"):
        parts.append("Opt-out recorded.")
    heard = sorted({i for labels in found["intents"].values() for i, _ in labels})
    if heard:
        parts.append("Customer " + ", ".join(_INTENT_WORDS.get(i, i) for i in heard) + ".")
    scores = list(found["sentiment"].values())
    if len(scores) >= 2:
        parts.append(f"Customer mood {_label(scores[0])} at the start, {_label(scores[-1])} at the end.")
    return " ".join(parts)


def run_signals(call: Call) -> dict[str, str]:
    """Write the signals, the customer's sentiment curve and the recording
    disclosure, so Audit, QA and Bot analytics read measured values."""
    import db
    from agent_core.guardrails import mentions_recording_disclosure

    found = detect(call)
    sentiment_version, nli_version = models.version(models.SENTIMENT), models.version(models.NLI)
    with db.engine.begin() as conn:
        conn.execute(text("DELETE FROM interaction_turn_signals WHERE interaction_id = :ix"),
                     {"ix": call.interaction_id})
        conn.execute(text("DELETE FROM interaction_sentiment WHERE interaction_id = :ix"),
                     {"ix": call.interaction_id})
        for turn_index, score in found["sentiment"].items():
            turn_id = call.turn_ids.get(turn_index)
            if turn_id is None:
                continue
            conn.execute(
                text("INSERT INTO interaction_turn_signals (id, interaction_id, transcript_turn_id, kind, label, "
                     "score, model_version) VALUES (:id, :ix, :t, 'sentiment', :l, :s, :v)"),
                {"id": db._id("ITS"), "ix": call.interaction_id, "t": turn_id, "l": _label(score),
                 "s": score, "v": sentiment_version},
            )
            conn.execute(
                text("INSERT INTO interaction_sentiment (id, interaction_id, at_sec, score, label) "
                     "VALUES (:id, :ix, :at, :s, :l)"),
                {"id": db._id("SEN"), "ix": call.interaction_id, "at": int(call.turn_at.get(turn_index, 0)),
                 "s": score, "l": _label(score)},
            )
            conn.execute(
                text("UPDATE interaction_transcript SET sentiment_delta = :s WHERE id = :t"),
                {"s": score, "t": turn_id},
            )
        for turn_index, labels in found["intents"].items():
            turn_id = call.turn_ids.get(turn_index)
            if turn_id is None:
                continue
            for intent, p in labels:
                conn.execute(
                    text("INSERT INTO interaction_turn_signals (id, interaction_id, transcript_turn_id, kind, "
                         "label, score, model_version) VALUES (:id, :ix, :t, 'intent', :l, :s, :v)"),
                    {"id": db._id("ITS"), "ix": call.interaction_id, "t": turn_id, "l": intent, "s": p,
                     "v": nli_version},
                )
            # The turn's headline intent, where the channel did not record one.
            top, p = labels[0]
            conn.execute(
                text("UPDATE interaction_transcript SET intent = :i, intent_score = :p "
                     "WHERE id = :t AND (intent IS NULL OR intent IN ('', 'out_of_scope', 'unknown'))"),
                {"i": top, "p": p, "t": turn_id},
            )
        # The call was rolled up when it was filed, before these intents
        # existed: again now, so primary intent and "resolved" are measured.
        # The engine's own disposition stands.
        import capture

        capture.rollup_interaction(conn, call.interaction_id, keep_disposition=True)
        scores = list(found["sentiment"].values())
        if scores:
            avg = sum(scores) / len(scores)
            conn.execute(
                text("UPDATE interactions SET avg_sentiment = :a, sentiment_label = :l WHERE id = :ix"),
                {"a": round(avg, 3), "l": _label(avg), "ix": call.interaction_id},
            )
        # Recording disclosure, with when it was said. The agent's words are
        # the evidence; the rule id is the one QA and Audit already read.
        said = next((t for t in call.turns if t.speaker == "bot" and mentions_recording_disclosure(t.text)), None)
        conn.execute(
            text("DELETE FROM interaction_disclosures WHERE interaction_id = :ix "
                 "AND label = 'Call recording notice' AND read_by_kind = 'bot'"),
            {"ix": call.interaction_id},
        )
        if call.bot_id and any(t.speaker == "bot" for t in call.turns):
            conn.execute(
                text("INSERT INTO interaction_disclosures (id, interaction_id, rule_id, label, read_at_sec, "
                     "read_by_kind, read_by_bot_id, read) VALUES (:id, :ix, "
                     "(SELECT id FROM compliance_rules WHERE id = 'r-rec'), 'Call recording notice', :at, 'bot', "
                     "(SELECT id FROM bots WHERE id = :bot), :read)"),
                {"id": db._id("DSC"), "ix": call.interaction_id,
                 "at": int(call.turn_at.get(said.index, 0)) if said else None,
                 "bot": call.bot_id, "read": said is not None},
            )
    with db.engine.begin() as conn:
        summary = call_summary(conn, call, found)
        conn.execute(text("UPDATE interactions SET summary = :s WHERE id = :ix"),
                     {"s": summary, "ix": call.interaction_id})
    logger.info("call_intel %s: %s customer turns scored, %s with intents", call.interaction_id,
                len(found["sentiment"]), len(found["intents"]))
    return {"sentiment": sentiment_version, "nli": nli_version}
