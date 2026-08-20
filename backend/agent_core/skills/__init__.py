"""First-party Agent Skills — signed packs, progressive disclosure, code-mode."""

from agent_core.skills.pack import SkillPack, approx_tokens, iter_first_party_packs, pack_for_slug
from agent_core.skills.sign import sign_hash, verify_signature

__all__ = [
    "SkillPack",
    "approx_tokens",
    "iter_first_party_packs",
    "pack_for_slug",
    "sign_hash",
    "verify_signature",
]
