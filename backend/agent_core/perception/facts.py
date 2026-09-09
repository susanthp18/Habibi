"""The fact vocabulary: what one turn may say, as codes and bands.

Two rules, both from §12.3.

**Codes and bands, never free text and never a raw float.** ``fact_value`` is
an enum, a band or a boolean. This table is retained for training and for the
regulator, so a transcript line in it is a second copy of the customer record
under a different retention class — and ``AccountFeatures.to_log`` already
holds exactly this discipline for the decision log.

**Every fact carries where it came from.** The intent, the sentiment band and
the suppression flags are ``borrower_utterance`` however deterministic the
classifier that produced them was: wrapping speech in a keyword matcher does
not launder it, which is the whole subject of R-INJ-1.

The four suppression flags are the ones ``policy.SPEECH_SUPPRESSES`` acts on,
and each maps to a permitted-action set rather than to a score. Everything else
here is recorded and does nothing — deliberately, because a fact that is
written but not acted on is the state a golden set eventually changes, and a
fact that acts before anybody mapped it is the state R-INJ-1 exists to prevent.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent_core import lexicon
from agent_core.feature_provenance import BORROWER_UTTERANCE

#: Bumped when the meaning of a fact key changes, exactly as the vector
#: versions are. A fact written at p1 and read at p2 under the same key is the
#: failure this prevents.
SCHEMA_VERSION = "p1"

#: Turn intents that are, in themselves, a request to be left alone about this
#: debt. Both are keyword intents that predate this module.
_SUPPRESSING_INTENT = {
    "dispute": "dispute_claimed",
    "hardship": "hardship_claimed",
}


@dataclass(frozen=True)
class Fact:
    """One typed observation from one turn."""

    key: str
    value: Any
    provenance: str = BORROWER_UTTERANCE
    confidence: float | None = None
    abstained: bool = False
    #: The provenance classes of every input the producing model consumed.
    #: Speech in, speech out, however many classifiers sat in between.
    input_provenance: tuple[str, ...] = (BORROWER_UTTERANCE,)


def from_understanding(understanding: Any, *, text: str = "") -> list[Fact]:
    """One turn's classification, as facts.

    ``understanding`` is an ``agent_core.understanding.TurnUnderstanding``,
    taken as ``Any`` so this module does not import it — the ranking path must
    not be able to reach an LLM client through a perception import, and the
    import contract test checks exactly that.

    ``text`` is the raw turn, read only by the deterministic opt-out lexicon.
    It is never stored.
    """
    facts: list[Fact] = [
        Fact("intent", str(getattr(understanding, "intent", "") or "unknown"),
             confidence=_confidence(understanding)),
        # The band, not the float. A signed sentiment to three decimal places
        # is a number somebody will eventually put in a model.
        Fact("sentiment_band", str(getattr(understanding, "sentiment_label", "") or "neutral")),
        Fact("language", str(getattr(understanding, "language", "") or "en")),
        Fact("abuse", bool(getattr(understanding, "abuse", False))),
        Fact("unresolved_repeat", bool(getattr(understanding, "unresolved_repeat", False))),
    ]

    # --- the four that suppress ---------------------------------------------
    if getattr(understanding, "legal", False):
        facts.append(Fact("legal_threat", True))
    flag = _SUPPRESSING_INTENT.get(str(getattr(understanding, "intent", "") or ""))
    if flag:
        facts.append(Fact(flag, True))
    if lexicon.withdraws_consent(text):
        facts.append(Fact("consent_withdrawal", True))
    return facts


def _confidence(understanding: Any) -> float | None:
    """The winning intent's score, or None where the classifier gave none.

    None rather than zero: a keyword pass that matched nothing has no opinion
    about how sure it is, and recording 0.0 would make an abstention look like
    a confident negative.
    """
    try:
        score = float(understanding.intent_score)
    except (AttributeError, TypeError, ValueError):
        return None
    return score if score > 0 else None
