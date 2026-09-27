"""Measure the PII detectors against a labelled set, before trusting a change.

    python -m call_intel.eval            # patterns + context + CRM + the PII model
    python -m call_intel.eval --no-model # without the model (the degraded path)

Each case is a short conversation (Indian collections calls: English,
Hindi-English code-mix, spoken and written digits, Devanagari numerals) with
the spans that must be masked, and -- as important -- text that must NOT be:
amounts, payment dates, the agent's own name. Reports recall per type,
precision overall, and the gate the release is held to:

* recall >= 0.98 on structured identifiers (card, aadhaar, pan, phone,
  account, secret, email, upi, ifsc),
* recall >= 0.90 on names, addresses and dates of birth,
* precision >= 0.90.

A span counts as found when a finding of the right type overlaps it; a
finding overlapping no labelled span is a false positive.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

from call_intel import pii

STRUCTURED = {"card", "aadhaar", "pan", "phone", "account", "secret", "email", "upi", "ifsc"}
GATE = {"structured": 0.98, "contextual": 0.90, "precision": 0.90}


def _aadhaar() -> str:
    """A 12-digit number with a valid Verhoeff check digit (not a real one)."""
    body = "23412341234"
    for d in "0123456789":
        if pii.verhoeff_ok(body + d):
            return body + d
    raise AssertionError("no check digit")


AADHAAR = _aadhaar()


@dataclass
class Case:
    turns: list[tuple[str, str]]  # (speaker, text)
    #: (turn index, type, exact substring that must be masked)
    gold: list[tuple[int, str, str]]
    crm: dict | None = None


CASES: list[Case] = [
    Case([("bot", "Please tell me the last four digits of your registered mobile."),
          ("customer", "Sure, nine nine zero seven.")], [(1, "secret", "nine nine zero seven")]),
    Case([("bot", "What is the OTP you just received?"), ("customer", "It is 482913.")],
         [(1, "secret", "482913")]),
    Case([("bot", "Can you confirm your date of birth?"), ("customer", "Fifteenth of August nineteen eighty seven.")],
         [(1, "dob", "Fifteenth of August nineteen eighty seven")]),
    Case([("customer", "My card number is 4111 1111 1111 1111 and it was declined.")],
         [(0, "card", "4111 1111 1111 1111")]),
    Case([("customer", "card five five zero zero zero zero five five five five five five five five five nine")],
         [(0, "card", "five five zero zero zero zero five five five five five five five five five nine")]),
    Case([("customer", f"Aadhaar hai {AADHAAR[:4]} {AADHAAR[4:8]} {AADHAAR[8:]}.")],
         [(0, "aadhaar", f"{AADHAAR[:4]} {AADHAAR[4:8]} {AADHAAR[8:]}")]),
    Case([("customer", "My PAN is ABCPE1234F.")], [(0, "pan", "ABCPE1234F")]),
    Case([("customer", "Call me on 98450 12345 after six.")], [(0, "phone", "98450 12345")]),
    Case([("customer", "mera number nau aath chaar paanch shunya ek do teen chaar paanch hai")],
         [(0, "phone", "nau aath chaar paanch shunya ek do teen chaar paanch")]),
    Case([("customer", "मेरा नंबर ९८४५०१२३४५ है")], [(0, "phone", "९८४५०१२३४५")]),
    Case([("customer", "Send it to rahul.mehta@gmail.com please.")], [(0, "email", "rahul.mehta@gmail.com")]),
    Case([("customer", "I paid by UPI to rahul.m@okhdfcbank yesterday.")], [(0, "upi", "rahul.m@okhdfcbank")]),
    Case([("customer", "The IFSC is HDFC0001234.")], [(0, "ifsc", "HDFC0001234")]),
    Case([("customer", "My account number is 50100234567890.")], [(0, "account", "50100234567890")]),
    Case([("bot", "Am I speaking with Anita Desai?"), ("customer", "Yes, this is Anita.")],
         [(0, "name", "Anita Desai"), (1, "name", "Anita")], crm={"name": ["Anita Desai"]}),
    Case([("customer", "Please speak to my husband Rajesh Kumar, he handles the loan.")],
         [(0, "name", "Rajesh Kumar")]),
    Case([("customer", "I live at 14 MG Road, Indiranagar, Bangalore 560038.")],
         [(0, "address", "14 MG Road, Indiranagar, Bangalore 560038")]),
    Case([("customer", "Address: Flat 3B, Lake View Apartments, Chennai 600041")],
         [(0, "address", "Flat 3B, Lake View Apartments, Chennai 600041")]),
    # Must NOT be masked: amounts, due dates, the agent persona, the bank.
    Case([("bot", "Hello, I'm Kaia from BigTapp Bank. Your overdue amount is twelve thousand four hundred rupees."),
          ("customer", "I can pay five thousand on the twenty ninth of September."),
          ("bot", "Thank you. I have noted a promise of 5,000 on 29 September 2026.")], []),
    Case([("customer", "My EMI is 12,500 and I have paid 3 instalments out of 24.")], []),
    Case([("customer", "Main paisa next week de dunga, abhi job chali gayi hai.")], []),
]


def run(use_model: bool = True) -> dict:
    found_by_type: dict[str, list[bool]] = {}
    false_positives = total_predicted = 0
    misses: list[str] = []
    for case in CASES:
        turns = [pii.Turn(i, s, t) for i, (s, t) in enumerate(case.turns)]
        spans = {}
        version = None
        if use_model:
            from call_intel import models, stages

            try:
                per_turn = models.pii_spans([t.text for t in turns], list(stages.MODEL_LABELS),
                                            threshold=stages.MODEL_THRESHOLD)
                spans = {t.index: [(e["start"], e["end"], stages.MODEL_LABELS.get(e["label"], "custom"),
                                    e["score"]) for e in ents] for t, ents in zip(turns, per_turn)}
                version = models.version(models.PII)
            except Exception as exc:
                print(f"model unavailable ({exc}); patterns only", file=sys.stderr)
        findings = pii.detect(turns, crm=case.crm, model_spans=spans, model_version=version,
                              allow_names=["Kaia", "BigTapp", "Bank"])
        gold_spans = []
        for ti, ptype, sub in case.gold:
            start = case.turns[ti][1].index(sub)
            gold_spans.append((ti, ptype, start, start + len(sub)))
        for ti, ptype, s, e in gold_spans:
            hit = any(f.turn_index == ti and f.type == ptype and f.start < e and f.end > s for f in findings)
            found_by_type.setdefault(ptype, []).append(hit)
            if not hit:
                misses.append(f"{ptype}: {case.turns[ti][1][s:e]!r}")
        for f in findings:
            total_predicted += 1
            if not any(f.turn_index == ti and f.start < e and f.end > s for ti, _, s, e in gold_spans):
                false_positives += 1
                misses.append(f"false positive {f.type}: {case.turns[f.turn_index][1][f.start:f.end]!r}")
    recall = {t: sum(v) / len(v) for t, v in sorted(found_by_type.items())}
    structured = [h for t, v in found_by_type.items() if t in STRUCTURED for h in v]
    contextual = [h for t, v in found_by_type.items() if t not in STRUCTURED for h in v]
    report = {
        "recall": recall,
        "structuredRecall": sum(structured) / len(structured),
        "contextualRecall": sum(contextual) / len(contextual),
        "precision": 1 - false_positives / total_predicted if total_predicted else 1.0,
        "notes": misses,
    }
    report["passes"] = (report["structuredRecall"] >= GATE["structured"]
                        and report["contextualRecall"] >= GATE["contextual"]
                        and report["precision"] >= GATE["precision"])
    return report


if __name__ == "__main__":
    import json

    out = run(use_model="--no-model" not in sys.argv)
    print(json.dumps(out, indent=2, ensure_ascii=False))
    sys.exit(0 if out["passes"] else 1)
