"""Find PII in what was said on a call.

Three detectors, merged, each finding carrying its detector and confidence:

1. **Validated patterns** on the *normalised* words. Speech-to-text writes
   numbers the way people say them ("nine eight four five", "double seven",
   "nineteen eighty seven", Devanagari or Arabic-Indic digits), so every turn
   is first rewritten with digits, keeping a map back to the original
   characters. Card numbers must pass Luhn, Aadhaar must pass Verhoeff, PAN
   must have a valid holder-type letter: a pattern alone is not a finding.
2. **Context.** Whatever the caller says right after the agent asks for an OTP,
   a PIN, the last digits of a number or a date of birth is a secret, however
   short.
3. **The customer's own record.** Their name, phone numbers, email, address
   and account ids, from the CRM, matched in the call. Very high precision in
   any language, because the value is known.

The PII model (``models.pii_spans``) adds contextual entities -- names,
addresses, dates of birth said in prose -- when it is available; without it
the first three still run, so a model outage degrades recall on prose, never
on identifiers.

Offsets are into the turn's original (unmasked) text.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Iterable

# ---------------------------------------------------------------------------
# Spoken numbers -> digits, with a map back to the original characters
# ---------------------------------------------------------------------------

_UNITS = {
    "zero": 0, "oh": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9,
    # Devanagari (Hindi, Marathi), Tamil and Arabic number words: unambiguous
    # in their own script, unlike romanised Hindi (see _HINDI_ROMAN).
    "शून्य": 0, "एक": 1, "दो": 2, "तीन": 3, "चार": 4, "पांच": 5, "पाँच": 5, "छह": 6, "छः": 6,
    "सात": 7, "आठ": 8, "नौ": 9,
    "பூஜ்ஜியம்": 0, "ஒன்று": 1, "இரண்டு": 2, "மூன்று": 3, "நான்கு": 4, "ஐந்து": 5, "ஆறு": 6,
    "ஏழு": 7, "எட்டு": 8, "ஒன்பது": 9,
    "صفر": 0, "واحد": 1, "اثنان": 2, "اثنين": 2, "ثلاثة": 3, "أربعة": 4, "اربعة": 4, "خمسة": 5,
    "ستة": 6, "سبعة": 7, "ثمانية": 8, "تسعة": 9,
}
#: Romanised Hindi digits collide with English ("do", "no", "sat"): used only
#: on a turn the engine marked as Hindi.
_HINDI_ROMAN = {
    "shunya": 0, "sunya": 0, "ek": 1, "do": 2, "teen": 3, "char": 4, "chaar": 4, "paanch": 5,
    "panch": 5, "chhe": 6, "chhah": 6, "che": 6, "saat": 7, "aath": 8, "nau": 9,
}
_TEENS = {
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
         "eighty": 80, "ninety": 90}
_ORDINALS = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7,
    "eighth": 8, "ninth": 9, "tenth": 10, "eleventh": 11, "twelfth": 12, "thirteenth": 13,
    "fourteenth": 14, "fifteenth": 15, "sixteenth": 16, "seventeenth": 17, "eighteenth": 18,
    "nineteenth": 19, "twentieth": 20, "thirtieth": 30,
}
_REPEAT = {"double": 2, "triple": 3}

_TOKEN = re.compile(r"\w+|[^\w\s]", re.UNICODE)
#: What may sit between the spoken parts of one number: "98451, 23456", "9-9-0-7".
_JOINER = re.compile(r"^[\s,\-.]*$")


@dataclass
class Normalised:
    text: str
    #: For each character of ``text``, the original [start, end) it came from.
    spans: list[tuple[int, int]] = field(default_factory=list)

    def original(self, start: int, end: int) -> tuple[int, int]:
        return self.spans[start][0], self.spans[end - 1][1]


def _ascii_digits(s: str) -> str:
    """Devanagari, Arabic-Indic, Tamil ... decimal digits as 0-9."""
    return "".join(str(unicodedata.digit(c)) if c.isdigit() and not c.isascii() else c for c in s)


def normalise(text: str, *, hindi: bool = False) -> Normalised:
    """``text`` with spoken numbers as digit strings. A run of number words
    and digits separated only by spaces, commas or dashes becomes one digit
    string, as it was dictated: "nine eight four five one two" -> "984512"."""
    # Romanised Hindi digits collide with English words ("do", "no"), so on a
    # turn not marked Hindi they count only inside a dictated run of three or
    # more number words -- code-mix is often transcribed under an English locale.
    units = {**_UNITS, **_HINDI_ROMAN}
    tokens = [(m.group(0), m.start(), m.end()) for m in _TOKEN.finditer(text)]
    out: list[str] = []
    spans: list[tuple[int, int]] = []
    pos = 0  # next original character not yet emitted

    def emit_original(upto: int) -> None:
        nonlocal pos
        for i in range(pos, upto):
            out.append(text[i])
            spans.append((i, i + 1))
        pos = max(pos, upto)

    i = 0
    while i < len(tokens):
        digits, j = _ordinal(tokens, i)
        if digits is None:
            digits, j = _number_run(tokens, i, units, text)
            if digits is not None and not hindi and j - i < 3 and any(
                    t[0].lower() in _HINDI_ROMAN and t[0].lower() not in _UNITS for t in tokens[i:j]):
                digits = None
        if digits is None:
            i += 1
            continue
        start, end = tokens[i][1], tokens[j - 1][2]
        emit_original(start)
        for ch in digits:
            out.append(ch)
            spans.append((start, end))
        pos = end
        i = j
    emit_original(len(text))
    return Normalised("".join(out), spans)


def _ordinal(tokens: list[tuple[str, int, int]], i: int) -> tuple[str | None, int]:
    """A spoken day of the month: "fifteenth" -> "15th", "twenty fifth" -> "25th"."""
    low = tokens[i][0].lower()
    if low in _ORDINALS:
        return f"{_ORDINALS[low]}th", i + 1
    if low in _TENS and i + 1 < len(tokens) and tokens[i + 1][0].lower() in _ORDINALS             and _ORDINALS[tokens[i + 1][0].lower()] < 10:
        return f"{_TENS[low] + _ORDINALS[tokens[i + 1][0].lower()]}th", i + 2
    return None, i


def _number_value(tokens: list[tuple[str, int, int]], i: int, units: dict[str, int]) -> tuple[str | None, int]:
    """(digits, tokens consumed) for the number starting at token ``i``."""
    word = tokens[i][0]
    low = word.lower()
    if _ascii_digits(word).isdigit():
        return _ascii_digits(word), 1
    if low in _REPEAT and i + 1 < len(tokens):
        nxt, used = _number_value(tokens, i + 1, units)
        if nxt is not None and len(nxt) == 1:
            return nxt * _REPEAT[low], 1 + used
        return None, 0
    if low in _TENS:
        value = _TENS[low]
        if i + 1 < len(tokens) and tokens[i + 1][0].lower() in units and units[tokens[i + 1][0].lower()] > 0 \
                and tokens[i + 1][1] - tokens[i][2] <= 2:
            return str(value + units[tokens[i + 1][0].lower()]), 2
        if i + 1 < len(tokens) and tokens[i + 1][0].lower() in _ORDINALS:
            return None, 0  # "twenty fifth": a date, handled by the ordinal pass
        return str(value), 1
    if low in _TEENS:
        return str(_TEENS[low]), 1
    if low in units:
        return str(units[low]), 1
    return None, 0


def _number_run(tokens, i, units, text) -> tuple[str | None, int]:
    first, used = _number_value(tokens, i, units)
    if first is None:
        return None, i
    digits, j = first, i + used
    while j < len(tokens):
        if not _JOINER.match(text[tokens[j - 1][2]:tokens[j][1]]) and tokens[j][0] not in (",", "-"):
            break
        k = j
        while k < len(tokens) and tokens[k][0] in (",", "-", "."):
            k += 1
        if k >= len(tokens):
            break
        nxt, used = _number_value(tokens, k, units)
        if nxt is None:
            break
        digits += nxt
        j = k + used
    return digits, j


# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------


def luhn_ok(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


_VERHOEFF_D = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 2, 3, 4, 0, 6, 7, 8, 9, 5], [2, 3, 4, 0, 1, 7, 8, 9, 5, 6],
    [3, 4, 0, 1, 2, 8, 9, 5, 6, 7], [4, 0, 1, 2, 3, 9, 5, 6, 7, 8], [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
    [6, 5, 9, 8, 7, 1, 0, 4, 3, 2], [7, 6, 5, 9, 8, 2, 1, 0, 4, 3], [8, 7, 6, 5, 9, 3, 2, 1, 0, 4],
    [9, 8, 7, 6, 5, 4, 3, 2, 1, 0],
]
_VERHOEFF_P = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 5, 7, 6, 2, 8, 3, 0, 9, 4], [5, 8, 0, 3, 7, 9, 6, 1, 4, 2],
    [8, 9, 1, 6, 0, 4, 3, 5, 2, 7], [9, 4, 5, 3, 1, 2, 6, 8, 7, 0], [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
    [2, 7, 9, 3, 8, 0, 6, 4, 1, 5], [7, 0, 4, 6, 9, 1, 3, 2, 5, 8],
]


def verhoeff_ok(digits: str) -> bool:
    c = 0
    for i, ch in enumerate(reversed(digits)):
        c = _VERHOEFF_D[c][_VERHOEFF_P[i % 8][int(ch)]]
    return c == 0


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------


@dataclass
class Finding:
    turn_index: int
    type: str
    start: int
    end: int
    confidence: float
    detector: str  # pattern | context | crm | model | custom
    model_version: str | None = None

    @property
    def needs_review(self) -> bool:
        return self.confidence < REVIEW_BELOW


#: A mask below this confidence is still applied, and flagged for a reviewer.
REVIEW_BELOW = 0.85

#: Every type's mask. Card keeps its last four, as printed on statements.
def mask_for(ptype: str, raw: str) -> str:
    if ptype == "card":
        tail = re.sub(r"\D", "", normalise(raw).text)[-4:]
        return f"**** **** **** {tail}" if len(tail) == 4 else "[CARD]"
    return {
        "aadhaar": "[AADHAAR]", "pan": "[PAN]", "phone": "[PHONE]", "email": "[EMAIL]",
        "address": "[ADDRESS]", "dob": "[DOB]", "account": "[ACCOUNT]", "ifsc": "[IFSC]",
        "pincode": "[PINCODE]", "name": "[NAME]", "upi": "[UPI]", "passport": "[PASSPORT]",
        "voter_id": "[VOTER-ID]", "driving_licence": "[DL]", "secret": "[REDACTED]",
    }.get(ptype, "[REDACTED]")


_MONTHS = ("jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|"
           "sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?")
_DAY = r"(?:[12]\d|3[01]|0?[1-9])"
_YEAR = r"((?:19|20)\d{2})"
_DATE = re.compile(
    rf"\b{_DAY}(?:st|nd|rd|th)?(?:\s+of)?\s+(?:{_MONTHS})\.?,?\s+{_YEAR}\b"
    rf"|\b(?:{_MONTHS})\.?\s+{_DAY}(?:st|nd|rd|th)?,?\s+{_YEAR}\b"
    rf"|\b{_DAY}[-/.](?:0?[1-9]|1[0-2])[-/.]{_YEAR}\b",
    re.I,
)
_DOB_CONTEXT = re.compile(r"\b(?:born|birth|dob|d\.o\.b|janm|जन्म)\b", re.I)

#: The agent asked for something secret: the caller's next answer is one.
_ASKS_SECRET = re.compile(
    r"\b(?:last|final|first)\s+(?:\w+\s+){0,2}(?:digits?|numbers?)\b"
    r"|\b(?:otp|one[- ]time\s+(?:pass(?:word|code)?|pin|code))\b"
    r"|\b(?:pin|mpin|cvv|cvc|password|passcode)\b|\bsecurity\s+(?:code|question|answer)\b"
    r"|\bmother'?s\s+maiden\b|\b(?:date\s+of\s+birth|birth\s*date|dob)\b",
    re.I,
)

_PATTERNS: list[tuple[str, re.Pattern[str], float]] = [
    ("email", re.compile(r"\b[\w.%+-]+@[a-z0-9.-]+\.[a-z]{2,}\b", re.I), 0.99),
    # A UPI id has a handle, not a domain: name@okhdfcbank, 98xxxxxx@ybl.
    ("upi", re.compile(r"\b[\w.-]{2,}@[a-z]{2,}\b(?!\.)", re.I), 0.9),
    # 4th letter is the holder type (P person, C company, H HUF ...).
    ("pan", re.compile(r"\b[A-Z]{3}[ABCFGHLJPT][A-Z]\d{4}[A-Z]\b", re.I), 0.97),
    ("ifsc", re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b", re.I), 0.95),
    ("passport", re.compile(r"(?i)(?<=passport)(?:\s+(?:number|no\.?|is))*\s+([A-Z]\d{7})\b"), 0.93),
    ("voter_id", re.compile(r"\b[A-Z]{3}\d{7}\b"), 0.85),
    ("driving_licence", re.compile(r"\b[A-Z]{2}[- ]?\d{2}[- ]?(?:19|20)\d{2}\d{7}\b"), 0.9),
    ("account", re.compile(r"\b(?:HDFC|BIGTAPP)-(?:CC|PL|RL|AL)-\d{4}\b", re.I), 0.95),
    ("address", re.compile(r"(?i)\b(?:address|addr)\s*:\s*[^\n]+"), 0.9),
]


def _numeric(run: str, *, pin_context: bool) -> tuple[str, float] | None:
    """What a bare digit string is, if anything."""
    n = len(run)
    if 13 <= n <= 19 and luhn_ok(run):
        return "card", 0.99
    if n == 12 and run[0] in "23456789" and verhoeff_ok(run):
        return "aadhaar", 0.99
    if n == 10 and run[0] in "6789":
        return "phone", 0.95
    if n == 12 and run.startswith("91") and run[2] in "6789":
        return "phone", 0.95
    if n == 6 and run[0] != "0" and pin_context:
        return "pincode", 0.9
    if 9 <= n <= 18:
        # A long digit run that is none of the above: account or card-like.
        return "account", 0.85 if n >= 11 else 0.75
    return None


_PIN_CONTEXT = re.compile(r"\b(?:pin\s*code|pincode|postal|zip)\b", re.I)


@dataclass
class Turn:
    index: int
    speaker: str  # 'customer' | 'bot'
    text: str
    language: str | None = None


def detect(turns: list[Turn], *, crm: dict[str, Any] | None = None,
           disabled: Iterable[str] = (), custom: Iterable[tuple[str, str]] = (),
           model_spans: dict[int, list[tuple[int, int, str, float]]] | None = None,
           model_version: str | None = None, allow_names: Iterable[str] = ()) -> list[Finding]:
    """All findings on the call. ``custom`` = (rule id, regex) a tenant added;
    ``model_spans`` = per turn (start, end, type, score) from the PII model;
    ``allow_names`` = words never masked as a name (the agent's persona, the bank)."""
    off = set(disabled)
    found: list[Finding] = []
    asked_secret = False
    allow = {a.lower() for a in allow_names if a}
    this_year = date.today().year
    for turn in turns:
        text = turn.text or ""
        norm = normalise(text, hindi=(turn.language or "").lower().startswith("hi"))
        answering = asked_secret and turn.speaker == "customer"
        pin_context = bool(_PIN_CONTEXT.search(text))

        for m in re.finditer(r"\d+", norm.text):
            kind = _numeric(m.group(0), pin_context=pin_context)
            if kind is None and answering and 3 <= len(m.group(0)) <= 8:
                kind = ("secret", 0.95)
            if kind:
                s, e = norm.original(m.start(), m.end())
                found.append(Finding(turn.index, kind[0], s, e, kind[1], "context" if kind[0] == "secret" else "pattern"))
        for m in _DATE.finditer(norm.text):
            year = int(next(g for g in m.groups() if g))
            s, e = norm.original(m.start(), m.end())
            if answering or _DOB_CONTEXT.search(text):
                found.append(Finding(turn.index, "dob", s, e, 0.95, "context"))
            elif year <= this_year - 15:
                found.append(Finding(turn.index, "dob", s, e, 0.75, "pattern"))
        for ptype, pattern, conf in _PATTERNS:
            for m in pattern.finditer(text):
                s, e = (m.start(1), m.end(1)) if pattern.groups else (m.start(), m.end())
                found.append(Finding(turn.index, ptype, s, e, conf, "pattern"))
        for rule_id, pattern in custom:
            for s, e in _custom_matches(pattern, text):
                found.append(Finding(turn.index, "custom", s, e, 0.9, f"custom:{rule_id}"))
        if crm:
            found.extend(_crm_matches(turn, norm, crm))
        for s, e, ptype, score in (model_spans or {}).get(turn.index, []):
            if ptype == "name" and text[s:e].strip().lower() in allow:
                continue
            found.append(Finding(turn.index, ptype, s, e, round(float(score), 3), "model", model_version))
        if turn.speaker == "bot":
            asked_secret = bool(_ASKS_SECRET.search(text))
        elif turn.speaker == "customer":
            asked_secret = False
    return merge([f for f in found if f.type not in off])


#: A tenant's pattern gets this long per turn; a pathological one is skipped,
#: never allowed to stall the worker.
CUSTOM_TIMEOUT_S = 0.2


def _custom_matches(pattern: str, text: str) -> list[tuple[int, int]]:
    try:
        import regex  # time-boxed matching; ships with the ml image

        return [(m.start(), m.end()) for m in regex.finditer(pattern, text, timeout=CUSTOM_TIMEOUT_S)
                if m.end() > m.start()]
    except ImportError:
        return [(m.start(), m.end()) for m in re.finditer(pattern, text) if m.end() > m.start()]
    except Exception:  # a bad pattern or a timeout: the rule is skipped for this turn
        return []


def _crm_matches(turn: Turn, norm: Normalised, crm: dict[str, Any]) -> list[Finding]:
    out: list[Finding] = []
    text = turn.text
    for ptype in ("phone", "account"):
        for value in crm.get(ptype) or []:
            digits = re.sub(r"\D", "", str(value))
            if len(digits) >= 8:
                digits = digits[-10:] if ptype == "phone" else digits
                for m in re.finditer(re.escape(digits), norm.text):
                    s, e = norm.original(m.start(), m.end())
                    out.append(Finding(turn.index, ptype, s, e, 0.99, "crm"))
    for email in crm.get("email") or []:
        for m in re.finditer(re.escape(str(email)), text, re.I):
            out.append(Finding(turn.index, "email", m.start(), m.end(), 0.99, "crm"))
    for name in crm.get("name") or []:
        parts = [p for p in re.split(r"\s+", str(name).strip()) if len(p) >= 3]
        # The full name first, then each part ("Anita", "Desai") on its own.
        for candidate in [str(name).strip(), *parts]:
            if len(candidate) < 3:
                continue
            for m in re.finditer(rf"(?<!\w){re.escape(candidate)}(?!\w)", text, re.I):
                out.append(Finding(turn.index, "name", m.start(), m.end(), 0.98, "crm"))
    for address in crm.get("address") or []:
        # Three consecutive address words said together is the address.
        words = [w for w in re.findall(r"\w+", str(address)) if len(w) >= 3]
        for k in range(len(words) - 2):
            pattern = r"\W+".join(re.escape(w) for w in words[k:k + 3])
            for m in re.finditer(pattern, text, re.I):
                out.append(Finding(turn.index, "address", m.start(), m.end(), 0.95, "crm"))
    return out


def merge(findings: list[Finding]) -> list[Finding]:
    """One finding per overlapping stretch of a turn: the widest span, typed
    by the most confident detector over it."""
    out: list[Finding] = []
    for f in sorted(findings, key=lambda f: (f.turn_index, f.start, -f.end)):
        last = out[-1] if out else None
        if last and last.turn_index == f.turn_index and f.start < last.end:
            if f.confidence > last.confidence:
                last.type, last.detector, last.confidence, last.model_version = (
                    f.type, f.detector, f.confidence, f.model_version)
            last.end = max(last.end, f.end)
            continue
        out.append(Finding(**f.__dict__))
    return out


def masked_text(text: str, findings: list[Finding]) -> str:
    """``text`` with each finding replaced by its mask."""
    out, pos = [], 0
    for f in sorted(findings, key=lambda f: f.start):
        if f.start < pos:
            continue
        out.append(text[pos:f.start])
        out.append(mask_for(f.type, text[f.start:f.end]))
        pos = f.end
    out.append(text[pos:])
    return "".join(out)


if __name__ == "__main__":
    n = normalise("my number is nine eight four five, one two three four five six ok")
    assert "9845123456" in n.text, n.text
    s, e = n.original(n.text.index("9845"), n.text.index("9845") + 10)
    assert n.text and "nine" in "my number is nine eight four five, one two three four five six ok"[s:e]
    assert normalise("double seven three").text == "773"
    assert normalise("born nineteen eighty seven").text == "born 1987"
    assert normalise("the twenty fifth of May").text == "the 25th of May"
    assert _DATE.search(normalise("fifteenth of August nineteen eighty seven").text)
    assert normalise("पिन ४००००१").text == "पिन 400001"
    assert luhn_ok("4111111111111111") and not luhn_ok("4111111111111112")
    assert verhoeff_ok("234123412346")
    turns = [
        Turn(0, "bot", "Hi, this is Kaia. Could you tell me the last four digits of your mobile?"),
        Turn(1, "customer", "Sure, nine nine zero seven. My card is 4111 1111 1111 1111."),
        Turn(2, "bot", "Thank you, Anita."),
        Turn(3, "customer", "I was born on 15th of August 1987 and my PAN is ABCPE1234F."),
        Turn(4, "customer", "We will pay twelve thousand four hundred on the twentieth of September 2026."),
    ]
    out = detect(turns, crm={"name": ["Anita Desai"]}, allow_names=["Kaia"])
    kinds = {(f.turn_index, f.type) for f in out}
    assert (1, "secret") in kinds and (1, "card") in kinds, kinds
    assert (2, "name") in kinds and (3, "dob") in kinds and (3, "pan") in kinds, kinds
    assert not any(f.turn_index == 4 for f in out), [f for f in out if f.turn_index == 4]
    assert not any(f.turn_index == 0 for f in out)
    assert masked_text(turns[1].text, [f for f in out if f.turn_index == 1]) == \
        "Sure, [REDACTED]. My card is **** **** **** 1111."
    print("ok", len(out), "findings")
