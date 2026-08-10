"""Explicit HL Assurance corpus manifest — no globs. Missing paths fail loud."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# Repo root: Hackathon/ (backend/scripts → parents[2]). In Docker the app lives
# at /app, so parents[2] is `/` — set SOURCE_DB_ROOT=/source_db (compose
# bind-mount of ../source_db) so ingest/reindex resolve corpus files.
_REPO_DEFAULT = Path(__file__).resolve().parents[2]
_SOURCE_OVERRIDE = (os.getenv("SOURCE_DB_ROOT") or "").strip()
REPO_ROOT = Path(_SOURCE_OVERRIDE).resolve() if _SOURCE_OVERRIDE else _REPO_DEFAULT


@dataclass(frozen=True)
class CorpusProduct:
    product_key: str
    title: str
    policy: str  # relative to REPO_ROOT (or absolute under SOURCE_DB_ROOT)
    faq: str
    benefits: str


# Every path is explicit. Fraud FAQ filename typo (FQAs) is intentional and listed.
CORPUS_MANIFEST: list[CorpusProduct] = [
    CorpusProduct(
        product_key="car",
        title="Car Protect360",
        policy="source_db/policy/Car_policy.md",
        faq="source_db/FAQ/Car_FAQs.txt",
        benefits="source_db/benefits/Car_benefits.txt",
    ),
    CorpusProduct(
        product_key="choice",
        title="Choice Protect360",
        policy="source_db/policy/Choice_policy.md",
        faq="source_db/FAQ/Choice_FAQs.txt",
        benefits="source_db/benefits/Choice_benefits.txt",
    ),
    CorpusProduct(
        product_key="early",
        title="Early Protect360 Plus",
        policy="source_db/policy/Early_policy.md",
        faq="source_db/FAQ/Early_FAQs.txt",
        benefits="source_db/benefits/Early_benefits.txt",
    ),
    CorpusProduct(
        product_key="fraud",
        title="Fraud Protect360",
        policy="source_db/policy/Fraud_policy.md",
        faq="source_db/FAQ/Fraud_FQAs.txt",
        benefits="source_db/benefits/Fraud_benefits.txt",
    ),
    CorpusProduct(
        product_key="home",
        title="Home Protect360",
        policy="source_db/policy/Home_policy.md",
        faq="source_db/FAQ/Home_FAQs.txt",
        benefits="source_db/benefits/Home_benefits.txt",
    ),
    CorpusProduct(
        product_key="hospital",
        title="Hospital Protect360",
        policy="source_db/policy/Hospital_policy.md",
        faq="source_db/FAQ/Hospital_FAQs.txt",
        benefits="source_db/benefits/Hospital_benefits.txt",
    ),
    CorpusProduct(
        product_key="maid",
        title="Maid Protect360",
        policy="source_db/policy/Maid_policy.md",
        faq="source_db/FAQ/Maid_FAQs.txt",
        benefits="source_db/benefits/Maid_benefits.txt",
    ),
    CorpusProduct(
        product_key="personal_accident",
        title="Personal Accident Protect360",
        policy="source_db/policy/PersonalAccident_policy.md",
        faq="source_db/FAQ/PersonalAccident_FAQs.txt",
        benefits="source_db/benefits/PersonalAccident_benefits.txt",
    ),
    CorpusProduct(
        product_key="travel",
        title="Travel Protect360",
        policy="source_db/policy/Travel_policy.md",
        faq="source_db/FAQ/Travel_FAQs.txt",
        benefits="source_db/benefits/Travel_benefits.txt",
    ),
    CorpusProduct(
        product_key="collections",
        title="HDFC Retail Collections",
        policy="source_db/policy/Collections_policy.md",
        faq="source_db/FAQ/Collections_FAQs.txt",
        benefits="source_db/benefits/Collections_benefits.txt",
    ),
]


class CorpusManifestError(FileNotFoundError):
    pass


def resolve_path(rel: str) -> Path:
    """Resolve a manifest-relative path.

    Manifest entries are ``source_db/...`` relative to the Hackathon repo root.
    When ``SOURCE_DB_ROOT`` points at the mounted corpus directory itself
    (``/source_db``), strip the leading ``source_db/`` segment.
    """
    p = Path(rel)
    if _SOURCE_OVERRIDE and p.parts and p.parts[0] == "source_db":
        p = Path(*p.parts[1:]) if len(p.parts) > 1 else Path(".")
        return (REPO_ROOT / p).resolve()
    return (_REPO_DEFAULT / rel).resolve()


def validate_manifest(manifest: list[CorpusProduct] = CORPUS_MANIFEST) -> list[tuple[CorpusProduct, dict[str, Path]]]:
    """Ensure every listed file exists and is non-empty.

    Every entry is checked; a single ``CorpusManifestError`` then reports all
    missing/empty files at once (it does not stop at the first gap).
    """
    resolved: list[tuple[CorpusProduct, dict[str, Path]]] = []
    errors: list[str] = []
    for product in manifest:
        paths = {
            "policy": resolve_path(product.policy),
            "faq": resolve_path(product.faq),
            "benefits": resolve_path(product.benefits),
        }
        for kind, path in paths.items():
            if not path.is_file():
                errors.append(f"{product.product_key}.{kind}: missing {path} (manifest={getattr(product, kind)})")
            elif path.stat().st_size == 0:
                errors.append(f"{product.product_key}.{kind}: empty file {path}")
        resolved.append((product, paths))
    if errors:
        raise CorpusManifestError(
            "Corpus manifest validation failed (" + str(len(errors)) + " issue(s)):\n- " + "\n- ".join(errors)
        )
    return resolved
