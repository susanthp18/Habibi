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
)

# No trailing \w* here: "court" must not match "courtesy", and unlike abuse
# there is no suffixed form worth catching ("suing" is already listed).
LEGAL_RE = re.compile(r"\b(?:" + "|".join(LEGAL_PATTERNS) + r")\b", re.I)


def is_abusive(text: str) -> bool:
    return bool(ABUSE_RE.search(text or ""))


def is_legal_threat(text: str) -> bool:
    return bool(LEGAL_RE.search(text or ""))


def abuse_hits(text: str) -> int:
    """Distinct abusive terms present. Used to weight the sentiment penalty.

    Distinct rather than total so a caller who says the same word four times is
    not scored four times more negatively than one who says it once — the
    escalation already fired on the first.
    """
    return len({m.group(0).lower() for m in ABUSE_RE.finditer(text or "")})
