"""Fish Audio S2 emotion, tone and effect markers.

Kept separate from the client so the registry can publish the palette as data
without importing an HTTP module, and so the UI's picker and the synthesiser
can never drift apart on what a valid tag looks like.

Syntax is ``[square brackets]`` on S2; legacy S1 used ``(parentheses)``. Tags
are stage directions — they are never spoken. Placement carries meaning: a tag
applies from where it sits onward, so ``[whispering] I didn't want to go in``
whispers the whole line while ``I didn't want to go [whispering] in`` whispers
only the last word.

These lists are a **starting palette, not a closed enum.** Fish accepts free-form
descriptions (``[laughing nervously while trying to keep composure]``), so any
UI built on this must let an operator type their own rather than only pick.
"""

from __future__ import annotations

#: Sentence-level feelings. Vendor guidance: put these at the start of a
#: sentence — mid-sentence they read as an abrupt switch rather than a mood.
EMOTION_TAGS_EMOTION: tuple[str, ...] = (
    "happy", "sad", "angry", "excited", "calm", "nervous", "confident",
    "surprised", "satisfied", "delighted", "scared", "worried", "upset",
    "frustrated", "depressed", "empathetic", "embarrassed", "disgusted",
    "moved", "proud", "relaxed", "grateful", "curious", "sarcastic",
)

EMOTION_TAGS_ADVANCED: tuple[str, ...] = (
    "disdainful", "unhappy", "anxious", "hysterical", "indifferent",
    "uncertain", "doubtful", "confused", "disappointed", "regretful",
    "guilty", "ashamed", "jealous", "envious", "hopeful", "optimistic",
    "pessimistic", "nostalgic", "lonely", "bored", "contemptuous",
    "sympathetic", "compassionate", "determined", "resigned",
)

#: Delivery rather than feeling. These may appear anywhere in the text.
EMOTION_TAGS_TONE: tuple[str, ...] = (
    "in a hurry tone", "shouting", "screaming", "whispering", "soft tone",
    "emphasis",
)

#: Non-verbal sounds the speaker makes.
EMOTION_TAGS_EFFECT: tuple[str, ...] = (
    "laughing", "chuckling", "sobbing", "crying loudly", "sighing",
    "groaning", "panting", "gasping", "yawning", "snoring", "clear throat",
)

#: Sounds around the speaker, plus timing.
EMOTION_TAGS_SCENE: tuple[str, ...] = (
    "audience laughing", "background laughter", "crowd laughing", "break",
    "long-break",
)

#: Vendor guidance: beyond three stacked emotions on one sentence the result
#: degrades rather than compounding.
MAX_TAGS_PER_SENTENCE = 3

#: Markers a regulated collections line should not use without a deliberate
#: decision. Not enforced here — this module is data — but published so the
#: guardrail layer and the UI can warn rather than discovering it in a QA scan.
#: An agent that shouts at a debtor is the delivery compliance exists to catch.
RESTRICTED_ON_COLLECTIONS: frozenset[str] = frozenset(
    {"angry", "shouting", "screaming", "contemptuous", "disdainful",
     "disgusted", "hysterical", "in a hurry tone"}
)

ALL_TAGS: tuple[str, ...] = (
    EMOTION_TAGS_EMOTION
    + EMOTION_TAGS_ADVANCED
    + EMOTION_TAGS_TONE
    + EMOTION_TAGS_EFFECT
    + EMOTION_TAGS_SCENE
)
