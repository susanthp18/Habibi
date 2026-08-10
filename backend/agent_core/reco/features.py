"""Customer + in-call signal vector.

This module is the plug-and-play seam. Everything downstream — candidates,
scoring, arbitration — depends only on :class:`CustomerFeatures` and
:class:`CallSignals`, never on a table name. A deployment with a different core
banking schema implements one :class:`FeatureProvider` and changes nothing else.

Two rules that matter more than they look:

* **Every field is nullable and ``None`` is a real value.** It means "we do not
  know", and the scorer must treat it as absent rather than substitute a zero.
  Guessing is how a customer with no payment history on file ends up ranked as
  though they had a terrible one.
* **The vector is versioned.** ``SCHEMA_VERSION`` is written into every decision
  log row, because a model trained on v1 features cannot be scored against v2
  ones and something has to be able to tell them apart later.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Mapping, Protocol

from sqlalchemy import text

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "v1"

# Transcript intents that signal the customer is open to product talk. These
# come from agent_core.intent, which both voice and WhatsApp already run on
# every customer turn — the strongest buying signal in the system, and it was
# being collected and thrown away.
_PRODUCT_INTENTS = frozenset({"upsell_opportunity", "product_faq"})
_HARDSHIP_INTENTS = frozenset({"hardship", "waiver_request"})


def _f(value: Any) -> float | None:
    """Decimal/str/None → float|None without inventing a zero."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class CustomerFeatures:
    """What we know about the customer, independent of this conversation."""

    customer_id: str
    schema_version: str = SCHEMA_VERSION

    # --- holdings -----------------------------------------------------------
    held_product_ids: frozenset[str] = frozenset()
    held_categories: frozenset[str] = frozenset()
    relationship_months: int | None = None
    account_count: int = 0

    # --- financial ----------------------------------------------------------
    outstanding: float | None = None
    minimum_due: float | None = None
    sanctioned_amount: float | None = None
    utilization: float | None = None
    dpd_worst: int | None = None
    dpd_best: int | None = None
    bucket: str | None = None
    on_time_payment_ratio: float | None = None
    months_since_last_payment: int | None = None

    # --- behavioural --------------------------------------------------------
    prior_leads_won: int = 0
    prior_leads_lost: int = 0
    open_lead_product_ids: frozenset[str] = frozenset()
    declined_product_ids: frozenset[str] = frozenset()
    offers_last_30d: int = 0
    last_offer_at: datetime | None = None
    open_dispute_count: int = 0
    # A customer pulling documents is doing paperwork on their own account.
    # The *kind* is what carries meaning: a statement is routine, whereas a
    # no-dues certificate or a foreclosure quote means they are preparing to
    # leave. Pitching new credit into that is the most tone-deaf thing the
    # engine could do, so the two are counted separately.
    document_requests_90d: int = 0
    closure_documents_90d: int = 0

    # --- consent / contactability ------------------------------------------
    dnd: bool = False
    consent_by_channel: Mapping[str, str] = field(default_factory=dict)
    # e.g. "morning" / "evening" — carried for the follow-up the lead creates,
    # not for scoring. A rep calling outside it is why a good lead goes cold.
    preferred_window: str | None = None

    # --- risk ---------------------------------------------------------------
    segment: str | None = None
    risk: str | None = None
    risk_score: int | None = None

    def to_log(self) -> dict[str, Any]:
        """PII-minimised snapshot for the decision log.

        Ids and money bands only — no names, no phone numbers, nothing free
        text. The log is retained for model training, so it must not become a
        second copy of the customer record.
        """
        return {
            "schemaVersion": self.schema_version,
            "heldProductIds": sorted(self.held_product_ids),
            "heldCategories": sorted(self.held_categories),
            "relationshipMonths": self.relationship_months,
            "accountCount": self.account_count,
            "outstanding": self.outstanding,
            "sanctionedAmount": self.sanctioned_amount,
            "utilization": self.utilization,
            "dpdWorst": self.dpd_worst,
            "dpdBest": self.dpd_best,
            "bucket": self.bucket,
            "onTimePaymentRatio": self.on_time_payment_ratio,
            "monthsSinceLastPayment": self.months_since_last_payment,
            "priorLeadsWon": self.prior_leads_won,
            "priorLeadsLost": self.prior_leads_lost,
            "declinedProductIds": sorted(self.declined_product_ids),
            "offersLast30d": self.offers_last_30d,
            "openDisputeCount": self.open_dispute_count,
            "documentRequests90d": self.document_requests_90d,
            "closureDocuments90d": self.closure_documents_90d,
            "dnd": self.dnd,
            "consentByChannel": dict(self.consent_by_channel),
            "preferredWindow": self.preferred_window,
            "segment": self.segment,
            "risk": self.risk,
            "riskScore": self.risk_score,
        }


@dataclass(frozen=True)
class CallSignals:
    """What this specific conversation has told us.

    This is the half a batch propensity model can never have, and it is usually
    the difference between a relevant offer and an irritating one. A caller who
    just said "can I get a top-up?" is a different prospect from the same
    customer on a different day.
    """

    interaction_id: str | None = None
    channel: str = "voice"
    intents_seen: tuple[str, ...] = ()
    dominant_intent: str | None = None
    sentiment_current: float = 0.0
    sentiment_trend: float = 0.0
    product_mentions: tuple[str, ...] = ()
    kb_topics_queried: tuple[str, ...] = ()
    commitment_secured: bool = False
    ptp_captured: bool = False
    escalation_flagged: bool = False
    dispute_opened: bool = False
    hardship_mentioned: bool = False
    offer_declined_this_call: bool = False
    offers_presented_this_call: int = 0
    customer_turns: int = 0

    @property
    def product_interest(self) -> bool:
        return bool(_PRODUCT_INTENTS.intersection(self.intents_seen))

    def to_log(self) -> dict[str, Any]:
        return {
            "channel": self.channel,
            "intentsSeen": list(self.intents_seen),
            "dominantIntent": self.dominant_intent,
            "sentimentCurrent": self.sentiment_current,
            "sentimentTrend": self.sentiment_trend,
            "productMentions": list(self.product_mentions),
            "kbTopicsQueried": list(self.kb_topics_queried),
            "commitmentSecured": self.commitment_secured,
            "ptpCaptured": self.ptp_captured,
            "escalationFlagged": self.escalation_flagged,
            "disputeOpened": self.dispute_opened,
            "hardshipMentioned": self.hardship_mentioned,
            "offerDeclinedThisCall": self.offer_declined_this_call,
            "offersPresentedThisCall": self.offers_presented_this_call,
            "customerTurns": self.customer_turns,
        }


class FeatureProvider(Protocol):
    """The seam. Implement this against your own schema and the rest works.

    ``conn`` is a *hint*, not a requirement: the engine has a database
    connection open anyway, and handing it over means one checkout per
    recommendation instead of two. A provider reading a REST API or a feature
    store ignores it and opens whatever it needs.
    """

    def build(
        self,
        customer_id: str,
        *,
        interaction_id: str | None = None,
        channel: str = "voice",
        live: "CallSignals | None" = None,
        conn: Any | None = None,
    ) -> tuple[CustomerFeatures, CallSignals]: ...


class PostgresFeatureProvider:
    """Default provider, reading the tables this deployment already has."""

    def build(
        self,
        customer_id: str,
        *,
        interaction_id: str | None = None,
        channel: str = "voice",
        live: CallSignals | None = None,
        conn: Any | None = None,
    ) -> tuple[CustomerFeatures, CallSignals]:
        import capture
        import db

        if conn is not None:
            return self._build_on(conn, customer_id, interaction_id, channel, live, capture)

        # Standalone use (tests, scripts, the replay harness). The engine
        # always supplies a connection: opening a second one per call doubled
        # pool checkouts, and at four concurrent calls against a pool of five
        # that pushed p99 from 100ms to 214ms — through the 150ms budget for a
        # reason that had nothing to do with the work being done.
        with db.engine.connect() as owned:
            return self._build_on(owned, customer_id, interaction_id, channel, live, capture)

    def _build_on(
        self,
        conn: Any,
        customer_id: str,
        interaction_id: str | None,
        channel: str,
        live: CallSignals | None,
        capture: Any,
    ) -> tuple[CustomerFeatures, CallSignals]:
        features = self._customer_features(conn, customer_id, capture=capture)
        signals = self._call_signals(
            conn,
            interaction_id=interaction_id,
            channel=channel,
            live=live,
        )
        return features, signals

    # ------------------------------------------------------------------ parts

    def _customer_features(self, conn: Any, customer_id: str, *, capture: Any) -> CustomerFeatures:
        snapshot = capture.account_snapshot(conn, customer_id)
        accounts = snapshot["accounts"]

        customer = (
            conn.execute(
                text(
                    "SELECT dnd, segment, risk, risk_score, preferred_window"
                    " FROM customers WHERE id = :id"
                ),
                {"id": customer_id},
            )
            .mappings()
            .first()
        ) or {}

        outstanding = sum(_f(a.get("outstanding")) or 0.0 for a in accounts) or None
        sanctioned = sum(_f(a.get("sanctioned_amount")) or 0.0 for a in accounts) or None
        minimum_due = sum(_f(a.get("minimum_due")) or 0.0 for a in accounts) or None
        utilization = (
            round(outstanding / sanctioned, 4)
            if outstanding is not None and sanctioned
            else None
        )

        opened = [a.get("opened_on") for a in accounts if a.get("opened_on")]
        relationship_months = None
        if opened:
            earliest = min(opened)
            if isinstance(earliest, datetime):
                delta = datetime.now(timezone.utc) - _aware(earliest)
                relationship_months = max(0, int(delta.days / 30.44))

        categories = set()
        if accounts:
            rows = conn.execute(
                text(
                    "SELECT DISTINCT COALESCE(category, type) AS c FROM products"
                    " WHERE id = ANY(:ids)"
                ),
                {"ids": sorted(snapshot["held_product_ids"])},
            ).mappings().all()
            categories = {str(r["c"]).lower() for r in rows if r.get("c")}

        lead_stats = (
            conn.execute(
                text(
                    """
                    SELECT
                      COUNT(*) FILTER (WHERE stage = 'won')::int AS won,
                      COUNT(*) FILTER (WHERE stage = 'lost')::int AS lost
                    FROM leads WHERE customer_id = :cid
                    """
                ),
                {"cid": customer_id},
            )
            .mappings()
            .first()
        ) or {}

        open_leads = {
            str(r["product_id"])
            for r in conn.execute(
                text(
                    "SELECT DISTINCT product_id FROM leads"
                    " WHERE customer_id = :cid AND stage = ANY(:stages)"
                    " AND product_id IS NOT NULL"
                ),
                {"cid": customer_id, "stages": list(db_open_stages())},
            ).mappings()
        }

        declined, offers_30d, last_offer_at = self._offer_history(conn, customer_id)

        disputes = (
            conn.execute(
                text(
                    "SELECT COUNT(*)::int AS n FROM disputes"
                    " WHERE customer_id = :cid AND status NOT IN ('resolved','rejected')"
                ),
                {"cid": customer_id},
            )
            .mappings()
            .first()
        ) or {}

        on_time, months_since = self._payment_behaviour(conn, customer_id)

        # doc_type is free text across deployments ("noc", "No-dues
        # certificate", "Restructuring quote"), so the closure test is a
        # keyword match on a normalised string rather than an enum lookup.
        docs = (
            conn.execute(
                text(
                    """
                    SELECT
                      COUNT(*)::int AS n,
                      COUNT(*) FILTER (
                        WHERE lower(replace(doc_type, '-', ' ')) ~
                              '(noc|no dues|foreclos|closure|settlement|restructur)'
                      )::int AS closing
                    FROM document_requests
                    WHERE customer_id = :cid AND created_at > now() - interval '90 days'
                    """
                ),
                {"cid": customer_id},
            )
            .mappings()
            .first()
        ) or {}

        return CustomerFeatures(
            customer_id=customer_id,
            held_product_ids=frozenset(snapshot["held_product_ids"]),
            held_categories=frozenset(categories),
            relationship_months=relationship_months,
            account_count=len(accounts),
            outstanding=outstanding,
            minimum_due=minimum_due,
            sanctioned_amount=sanctioned,
            utilization=utilization,
            dpd_worst=snapshot["dpd_worst"],
            dpd_best=snapshot["dpd_best"],
            bucket=(snapshot["primary"] or {}).get("bucket"),
            on_time_payment_ratio=on_time,
            months_since_last_payment=months_since,
            prior_leads_won=int(lead_stats.get("won") or 0),
            prior_leads_lost=int(lead_stats.get("lost") or 0),
            open_lead_product_ids=frozenset(open_leads),
            declined_product_ids=frozenset(declined),
            offers_last_30d=offers_30d,
            last_offer_at=last_offer_at,
            open_dispute_count=int(disputes.get("n") or 0),
            document_requests_90d=int(docs.get("n") or 0),
            closure_documents_90d=int(docs.get("closing") or 0),
            dnd=bool(customer.get("dnd")),
            consent_by_channel=capture.latest_consent_by_channel(conn, customer_id),
            preferred_window=customer.get("preferred_window"),
            segment=customer.get("segment"),
            risk=customer.get("risk"),
            risk_score=customer.get("risk_score"),
        )

    def _offer_history(
        self, conn: Any, customer_id: str
    ) -> tuple[set[str], int, datetime | None]:
        """Declines and offer frequency, from the decision log first and the
        commercial-event stream second.

        Both are consulted because the decision log only starts when the engine
        does — leads captured before it existed still carry an offer_presented
        event, and forgetting those would let the engine re-pitch something the
        customer already refused.
        """
        declined: set[str] = set()
        last_offer_at: datetime | None = None
        offers_30d = 0
        cutoff = datetime.now(timezone.utc) - timedelta(days=30)

        try:
            rows = conn.execute(
                text(
                    """
                    SELECT chosen_product_id, response, presented, created_at
                    FROM offer_decisions
                    WHERE customer_id = :cid AND created_at > now() - interval '180 days'
                    ORDER BY created_at DESC
                    LIMIT 200
                    """
                ),
                {"cid": customer_id},
            ).mappings().all()
        except Exception:
            # Table not migrated yet — degrade to the event stream rather than
            # failing the whole recommendation.
            logger.debug("offer_decisions unavailable; using activity_events", exc_info=True)
            rows = []

        for r in rows:
            if r.get("response") == "declined" and r.get("chosen_product_id"):
                declined.add(str(r["chosen_product_id"]))
            if r.get("presented"):
                at = r.get("created_at")
                if isinstance(at, datetime):
                    at = _aware(at)
                    last_offer_at = max(last_offer_at or at, at)
                    if at > cutoff:
                        offers_30d += 1

        events = conn.execute(
            text(
                """
                SELECT ae.kind, ae.at, ae.payload ->> 'productId' AS product_id
                FROM activity_events ae
                LEFT JOIN interactions i ON i.id = ae.entity_id AND ae.entity_type = 'interaction'
                WHERE ae.kind IN ('offer_presented', 'offer_declined')
                  AND (i.customer_id = :cid OR (ae.entity_type = 'customer' AND ae.entity_id = :cid))
                  AND ae.at > now() - interval '180 days'
                ORDER BY ae.at DESC
                LIMIT 200
                """
            ),
            {"cid": customer_id},
        ).mappings().all()

        for e in events:
            pid = e.get("product_id")
            if e["kind"] == "offer_declined" and pid:
                declined.add(str(pid))
            elif e["kind"] == "offer_presented":
                at = e.get("at")
                if isinstance(at, datetime):
                    at = _aware(at)
                    last_offer_at = max(last_offer_at or at, at)
                    if at > cutoff:
                        offers_30d += 1

        return declined, offers_30d, last_offer_at

    def _payment_behaviour(self, conn: Any, customer_id: str) -> tuple[float | None, int | None]:
        """On-time ratio and recency, from the ledger.

        Returns (None, None) when there is no payment history rather than a
        flattering or damning default — an unknown payer is not a good payer.
        """
        try:
            row = (
                conn.execute(
                    text(
                        """
                        SELECT
                          COUNT(*) FILTER (WHERE le.type = 'payment')::int AS payments,
                          COUNT(*) FILTER (WHERE le.type = 'fee')::int AS fees,
                          MAX(le.posted_at) FILTER (WHERE le.type = 'payment') AS last_payment_at
                        FROM ledger_entries le
                        JOIN accounts a ON a.id = le.account_id
                        WHERE a.customer_id = :cid
                          AND le.posted_at > now() - interval '365 days'
                        """
                    ),
                    {"cid": customer_id},
                )
                .mappings()
                .first()
            )
        except Exception:
            logger.debug("ledger_entries unreadable for %s", customer_id, exc_info=True)
            return None, None

        if not row or not row.get("payments"):
            return None, None

        payments = int(row["payments"] or 0)
        fees = int(row["fees"] or 0)
        # Late-fee events per payment as a crude punctuality proxy. Crude is
        # fine; inventing a number is not.
        ratio = round(max(0.0, min(1.0, 1.0 - (fees / payments))), 4) if payments else None

        months_since = None
        last = row.get("last_payment_at")
        if isinstance(last, datetime):
            months_since = max(0, int((datetime.now(timezone.utc) - _aware(last)).days / 30.44))
        return ratio, months_since

    def _call_signals(
        self,
        conn: Any,
        *,
        interaction_id: str | None,
        channel: str,
        live: CallSignals | None,
    ) -> CallSignals:
        """Merge what the running call knows with what the transcript records.

        ``live`` is authoritative for anything the caller can only know
        in-process (commitment_secured, whether a pitch was already refused this
        turn). The transcript fills in the rest.
        """
        if not interaction_id:
            return live or CallSignals(channel=channel)

        rows = conn.execute(
            text(
                """
                SELECT speaker, intent, sentiment_delta, text
                FROM interaction_transcript
                WHERE interaction_id = :id
                ORDER BY turn_index
                """
            ),
            {"id": interaction_id},
        ).mappings().all()

        intents = tuple(
            str(r["intent"]) for r in rows if r.get("intent") and r["speaker"] == "customer"
        )
        customer_turns = sum(1 for r in rows if r["speaker"] == "customer")

        deltas = [_f(r.get("sentiment_delta")) for r in rows if r.get("sentiment_delta") is not None]
        deltas = [d for d in deltas if d is not None]
        sentiment_current = deltas[-1] if deltas else 0.0
        # Slope over the last three readings: a caller warming up and a caller
        # cooling down can sit at the same absolute score.
        recent = deltas[-3:]
        sentiment_trend = (recent[-1] - recent[0]) if len(recent) >= 2 else 0.0

        flags = (
            conn.execute(
                text(
                    "SELECT ptp_captured, upsell_presented, primary_intent"
                    " FROM interactions WHERE id = :id"
                ),
                {"id": interaction_id},
            )
            .mappings()
            .first()
        ) or {}

        dominant = None
        if intents:
            dominant = max(set(intents), key=intents.count)

        merged = CallSignals(
            interaction_id=interaction_id,
            channel=channel,
            intents_seen=intents,
            dominant_intent=dominant or flags.get("primary_intent"),
            sentiment_current=sentiment_current,
            sentiment_trend=sentiment_trend,
            product_mentions=_product_mentions(conn, rows),
            kb_topics_queried=_kb_topics_queried(conn, interaction_id),
            ptp_captured=bool(flags.get("ptp_captured")),
            hardship_mentioned=bool(_HARDSHIP_INTENTS.intersection(intents)),
            customer_turns=customer_turns,
        )
        if live is None:
            return merged

        # In-process truth wins where it exists; OR the booleans so a signal
        # observed by either source survives.
        return CallSignals(
            interaction_id=interaction_id,
            channel=live.channel or channel,
            intents_seen=merged.intents_seen or live.intents_seen,
            dominant_intent=live.dominant_intent or merged.dominant_intent,
            sentiment_current=(
                live.sentiment_current if live.sentiment_current else merged.sentiment_current
            ),
            sentiment_trend=live.sentiment_trend or merged.sentiment_trend,
            product_mentions=merged.product_mentions or live.product_mentions,
            kb_topics_queried=merged.kb_topics_queried or live.kb_topics_queried,
            commitment_secured=live.commitment_secured,
            ptp_captured=live.ptp_captured or merged.ptp_captured,
            escalation_flagged=live.escalation_flagged,
            dispute_opened=live.dispute_opened,
            hardship_mentioned=live.hardship_mentioned or merged.hardship_mentioned,
            offer_declined_this_call=live.offer_declined_this_call,
            offers_presented_this_call=live.offers_presented_this_call,
            customer_turns=max(live.customer_turns, merged.customer_turns),
        )


def _aware(value: datetime) -> datetime:
    """Treat a naive timestamp as UTC. Comparing naive and aware datetimes
    raises, and one stray naive row would take the whole recommendation down."""
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _product_mentions(conn: Any, rows: list[Mapping[str, Any]]) -> tuple[str, ...]:
    """Product ids the customer named out loud.

    A direct ask ("can I get a top-up?") is the single strongest signal
    available and it costs one query to notice. Matching is on the product name
    and on the id with separators relaxed, which is deliberately conservative:
    a missed mention only forgoes a bonus, whereas a false match would pitch
    the wrong product.
    """
    said = " ".join(
        str(r.get("text") or "").lower() for r in rows if r.get("speaker") == "customer"
    )
    if not said.strip():
        return ()
    try:
        products = conn.execute(
            text("SELECT id, name FROM products WHERE is_active IS TRUE")
        ).mappings().all()
    except Exception:
        return ()

    hits: list[str] = []
    for p in products:
        name = str(p["name"] or "").lower().strip()
        pid = str(p["id"] or "").lower().replace("-", " ").replace("_", " ").strip()
        if (name and len(name) > 3 and name in said) or (pid and len(pid) > 3 and pid in said):
            hits.append(str(p["id"]))
    return tuple(hits)


def _kb_topics_queried(conn: Any, interaction_id: str) -> tuple[str, ...]:
    """Knowledge-base topics the customer pulled up during this call.

    Read from the ``product_interest`` events kb.py emits, which carry the doc
    types of the passages the model was actually shown. Ordered by first
    appearance so the log is stable across replays of the same call.
    """
    try:
        rows = conn.execute(
            text(
                """
                SELECT payload -> 'topics' AS topics
                FROM activity_events
                WHERE entity_type = 'interaction'
                  AND entity_id = :id
                  AND kind = 'product_interest'
                ORDER BY at
                """
            ),
            {"id": interaction_id},
        ).mappings().all()
    except Exception:
        logger.debug("kb topics unreadable for %s", interaction_id, exc_info=True)
        return ()

    out: list[str] = []
    for r in rows:
        topics = r.get("topics")
        if not isinstance(topics, list):
            continue
        for t in topics:
            topic = str(t or "").strip().lower()
            if topic and topic not in out:
                out.append(topic)
    return tuple(out)


def db_open_stages() -> tuple[str, ...]:
    import db

    return tuple(db.OPEN_LEAD_STAGES)


_DEFAULT_PROVIDER: FeatureProvider = PostgresFeatureProvider()


def build_features(
    customer_id: str,
    *,
    interaction_id: str | None = None,
    channel: str = "voice",
    live: CallSignals | None = None,
    provider: FeatureProvider | None = None,
    conn: Any | None = None,
) -> tuple[CustomerFeatures, CallSignals]:
    """Build the vectors, reusing ``conn`` when the caller already holds one.

    ``conn`` is passed positionally-by-keyword and tolerated as unsupported:
    a custom provider written before this parameter existed keeps working, it
    just opens its own connection as it always did.
    """
    target = provider or _DEFAULT_PROVIDER
    try:
        return target.build(
            customer_id,
            interaction_id=interaction_id,
            channel=channel,
            live=live,
            conn=conn,
        )
    except TypeError:
        # An older provider that does not accept `conn`. Retrying without it is
        # the difference between a slower recommendation and none at all.
        logger.debug("feature provider %r does not accept conn", type(target).__name__)
        return target.build(
            customer_id, interaction_id=interaction_id, channel=channel, live=live
        )
