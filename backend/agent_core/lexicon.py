"""One abuse/legal lexicon for every channel.

Three independent copies had grown, and they disagreed in ways that mattered
because both feed *compliance escalation*, not cosmetics:

``voice/safety.py``
    The narrowest and most battle-tested. Two of its patterns exist because the
    obvious version misfired on real calls: ``kill`` requires an explicit target
    (a bare ``\\bkill\\b`` escalated "kill the deal" and "killing time"), and
    ``fir`` requires police/complaint context (a bare ``\\bfir\\b`` escalated
    "fir se try karo", where *fir* is the Hinglish spelling of फिर, "then").
``agent_core/sentiment.py``
    Matched abuse by bare substring while scoring positive and negative words
    with word boundaries — so "skill" contained "kill" and any word containing
    a lexicon term scored as abuse.
``bot_runtime.py``
    A hardcoded eight-word tuple checked with ``in``, missing most of the terms
    the other two carried.

This module keeps the voice narrowing and the word-boundary matcher, and takes
the union of the three term lists.

The trailing ``\\w*`` is deliberate and load-bearing. ``guardrails.py`` added it
so suffixed forms trip the same rule — "harassment" from *harass*, "fucked"
from *fuck* — and a plain trailing ``\\b`` (as voice/safety.py had) would silently
drop those. The *leading* ``\\b`` is what keeps "skill" from matching *kill*.
"""

from __future__ import annotations

import re

# Regex fragments, not plain words: several entries need alternation or an
# explicit target, which a substring list cannot express.
ABUSE_PATTERNS: tuple[str, ...] = (
    r"stfu",
    r"fuck(?:ing)?",
    r"motherfucker",
    r"shit",
    r"idiot",
    r"stupid",
    r"shut\s*up",
    r"asshole",
    r"bastard",
    r"son\s+of\s+a\s+bitch",
    r"bloody\s+hell",
    r"go\s+to\s+hell",
    r"damn\s+you",
    # Requires a target. See the module docstring.
    r"kill\s+(?:you|yourself)",
    r"harass",
    r"madarchod",
    r"behenchod",
    r"bhenchod",
    r"chutiya",
    r"harami",
    r"gandu",
)

# Human-readable surface forms. Kept because it is the documented, importable
# shape (``agent_core.sentiment.ABUSE_LEXICON``) and reads far better in a
# review than the pattern tuple. ABUSE_RE is the matcher; this is the label.
ABUSE_LEXICON: tuple[str, ...] = (
    "stfu",
    "fuck",
    "fucking",
    "motherfucker",
    "shit",
    "idiot",
    "stupid",
    "shut up",
    "asshole",
    "bastard",
    "son of a bitch",
    "bloody hell",
    "go to hell",
    "damn you",
    "kill yourself",
    "harass",
    "madarchod",
    "behenchod",
    "chutiya",
    "harami",
    "gandu",
)

ABUSE_RE = re.compile(r"\b(?:" + "|".join(ABUSE_PATTERNS) + r")\w*", re.I)

LEGAL_PATTERNS: tuple[str, ...] = (
    r"lawyer",
    r"advocate",
    r"attorney",
    r"solicitor",
    r"court",
    r"lawsuit",
    r"sue\s+you",
    r"suing",
    r"legal\s+action",
    r"consumer\s+forum",
    r"ombudsman",
    r"cyber\s*cell",
    r"rbi\s+complaint",
    r"police\s+complaint",
    # An actual First Information Report always carries police/complaint
    # context. Requiring it is what keeps "fir se try karo" out. See docstring.
    r"(?:file|lodge|register|filing|lodging|registering)\s+(?:an?\s+)?fir\b",
    r"fir\s+(?:against|karunga|karoonga|kar\s+doonga|complaint|lodge|file)\b",
    r"police\s+(?:me[in]?\s+)?fir\b",
    # Hinglish / Indic legal. ``vakil`` / ``adalat`` are the spoken forms the
    # English ``lawyer`` / ``court`` patterns miss; courtesy-like substrings
    # are not listed.
    r"vakil",
    r"vakeel",
    r"adalat",
    r"nyayalay",
    r"kacheri",
    r"वकील",
    r"अदालत",
    r"न्यायालय",
    r"वக்கீல்",
    r"நீதிமன்றம்",
)

# No trailing \w* here: "court" must not match "courtesy", and unlike abuse
# there is no suffixed form worth catching ("suing" is already listed).
LEGAL_RE = re.compile(r"\b(?:" + "|".join(LEGAL_PATTERNS) + r")\b", re.I)


#: "Stop calling me." §12.3's own worked example of the one direction a
#: borrower's words are always safe to act on: a withdrawal can only ever
#: restrict what we do, so a false positive costs us a contact and a false
#: negative costs the borrower a call they asked not to receive.
#:
#: Hinglish included because the deployment is, and because a withdrawal
#: spoken in Hindi is a withdrawal. ``mat karo`` / ``mat karna`` (don't do it),
#: ``band karo`` (stop it), ``pareshan mat karo`` (stop bothering me).
#: A deferral is not a withdrawal. "Don't call me right now / today / this
#: evening" asks for a pause, not DND. Permanent forms ("stop calling me",
#: "never call me") still match because they have no temporal tail.
_NOT_TEMPORAL = (
    r"(?!\s+(?:right\s+now|now|today|tonight|tomorrow|later|"
    r"this\s+(?:evening|morning|afternoon|week)|"
    r"in\s+a\s+(?:bit|minute|while)))"
)

OPTOUT_PATTERNS: tuple[str, ...] = (
    r"(?:stop|quit|cease)\s+(?:calling|call|ringing|contacting|messaging|texting)"
    + _NOT_TEMPORAL,
    r"(?:don'?t|do\s+not|never)\s+(?:call|ring|contact|message|text)\s+(?:me|again)"
    + _NOT_TEMPORAL,
    r"(?:take|remove)\s+me\s+off\s+(?:your\s+)?(?:list|database)",
    r"remove\s+my\s+(?:number|contact)",
    r"unsubscribe",
    r"opt\s*-?\s*out",
    r"add\s+me\s+to\s+(?:the\s+)?dnd",
    r"(?:call|phone|contact|message)\s+mat\s+kar(?:o|na|iye)",
    r"(?:call|phone)\s+band\s+kar(?:o|na|iye|do)",
    r"pareshan\s+mat\s+kar(?:o|na|iye)",
)

#: No trailing ``\w*``: every pattern above already ends on a whole word, and a
#: suffix wildcard on ``opt out`` would match ``opt outside``.
OPTOUT_RE = re.compile(r"\b(?:" + "|".join(OPTOUT_PATTERNS) + r")\b", re.I)

# Indic scripts do not play well with ``\b`` (virama / matra are ``\w``, but
# callers type them in combinations the ASCII-oriented wrapper then misses).
_INDIC_ABUSE_RE = re.compile(r"मादरचोद|भेनचोद|चूतिया|हरामी")
_INDIC_LEGAL_RE = re.compile(r"वकील|अदालत|न्यायालय|வக்கீல்|நீதிமன்றம்")
_INDIC_OPTOUT_RE = re.compile(
    r"कॉल\s+मत\s+कर(?:ो|ना|िए)|फोन\s+मत\s+कर(?:ो|ना|िए)|कॉल\s+बंद\s+कर(?:ो|ना|िए|दो)"
)


def is_abusive(text: str) -> bool:
    raw = text or ""
    return bool(ABUSE_RE.search(raw) or _INDIC_ABUSE_RE.search(raw))


def withdraws_consent(text: str) -> bool:
    """Did the caller ask us to stop contacting them?

    Deterministic on purpose. §12.5's hard rule is that a regulatory constraint
    is never a model: a supervisor does not accept a false-negative rate on
    "stop calling me", and no golden set is needed to justify a regex that can
    only ever suppress.
    """
    raw = text or ""
    return bool(OPTOUT_RE.search(raw) or _INDIC_OPTOUT_RE.search(raw))


def is_legal_threat(text: str) -> bool:
    raw = text or ""
    return bool(LEGAL_RE.search(raw) or _INDIC_LEGAL_RE.search(raw))


def abuse_hits(text: str) -> int:
    """Distinct abusive terms present. Used to weight the sentiment penalty.

    Distinct rather than total so a caller who says the same word four times is
    not scored four times more negatively than one who says it once — the
    escalation already fired on the first.
    """
    return len({m.group(0).lower() for m in ABUSE_RE.finditer(text or "")})


def spoken_language(text: str) -> str:
    """Keyword-floor language tag for :class:`TurnUnderstanding`.

    ``en`` / ``hi`` / ``other`` — the three values the understanding merge
    already accepts. Script only: Latin Hinglish stays ``en`` here so a single
    ``haan`` does not flip the stored language.
    """
    raw = text or ""
    if re.search(r"[\u0900-\u097F]", raw):
        return "hi"
    if re.search(
        r"[\u0980-\u09FF\u0A80-\u0AFF\u0B80-\u0BFF\u0C00-\u0C7F\u0C80-\u0CFF\u0D00-\u0D7F]",
        raw,
    ):
        return "other"
    return "en"
