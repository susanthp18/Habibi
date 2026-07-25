"""Explicit HL Assurance corpus manifest — no globs. Missing paths fail loud."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# Repo root: Hackathon/
REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class CorpusProduct:
    product_key: str
    title: str
    policy: str  # relative to REPO_ROOT
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
    return (REPO_ROOT / rel).resolve()


def validate_manifest(manifest: list[CorpusProduct] = CORPUS_MANIFEST) -> list[tuple[CorpusProduct, dict[str, Path]]]:
    """Ensure every listed file exists and is non-empty. Raises CorpusManifestError on first gap."""
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
