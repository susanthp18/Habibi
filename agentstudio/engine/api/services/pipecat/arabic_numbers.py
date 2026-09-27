"""Whole amounts in Arabic replies are spoken as words, not read from digits.

Azure's Arabic voices voice a digit string such as "375 درهم" in a form its
own Arabic recognizer does not recover, while the same amount written in
standard Arabic words ("ثلاثمائة و خمسة و سبعون") is spoken and recognized
exactly. An amount is the one thing a collections call must not garble, so
a whole amount inside Arabic text is spelled out before synthesis. Only
amounts: a number next to a currency or the word for "amount", or written with
thousands separators. Account, reference and phone numbers stay digits, read
out as they are. Decimals and short numbers (days of the month) are left to
the voice, which reads them reliably.
"""

from __future__ import annotations

import re

from num2words import num2words
from pipecat.utils.text.base_text_filter import BaseTextFilter

_ARABIC_LETTER = re.compile(r"[؀-ۿݐ-ݿࢠ-ࣿ]")
# 1,250 / 12,500 / 375 / ١٢٥٠٠ -- but not part of a decimal ("3750.50") or a
# date/time ("15-10-2026", "10:30").
_WHOLE_NUMBER = re.compile(r"(?<![\d.,:\-/])(\d{1,3}(?:[,٬]\d{3})+|\d{3,})(?![\d.,:\-/]*\d)")


# Currencies a collections call quotes, in Arabic and Latin script, with the
# Arabic definite article or "by/with" prefix allowed ("بالدرهم", "الريال").
_CURRENCY = (r"(?:و?[بل]?(?:ال)?(?:درهم|دراهم|ريال|دينار|دنانير|جنيه|روبية|روبيات|دولار)"
             r"|د\.إ|ر\.س|AED|Dhs?|SAR|INR|Rs\.?|USD|₹|\$)")
_AMOUNT_BEFORE = re.compile(rf"(?:{_CURRENCY}|مبلغ|المبلغ|بمبلغ)\s*$")
_AMOUNT_AFTER = re.compile(rf"\s*{_CURRENCY}")


def _is_amount(text: str, match: re.Match) -> bool:
    if not match.group(1).isdigit():  # written with thousands separators
        return True
    return bool(_AMOUNT_BEFORE.search(text[max(0, match.start() - 12):match.start()])
                or _AMOUNT_AFTER.match(text, match.end()))


def spell_arabic_amounts(text: str) -> str:
    if not _ARABIC_LETTER.search(text):
        return text

    def words(match: re.Match) -> str:
        if not _is_amount(text, match):
            return match.group(0)
        digits = "".join(str(int(ch)) for ch in match.group(1) if ch.isdigit())
        return num2words(int(digits), lang="ar")

    return _WHOLE_NUMBER.sub(words, text)


class ArabicAmountsFilter(BaseTextFilter):
    """TTS text filter applying :func:`spell_arabic_amounts`."""

    async def filter(self, text: str) -> str:
        return spell_arabic_amounts(text)
