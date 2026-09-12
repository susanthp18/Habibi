"""Both halves of a resolved mouth in one dict, for the tests that pin both.

The runtime asks ``resolve_mouth`` for the half it needs; these tests want the
prompt and the tools of the same resolution side by side.
"""

from __future__ import annotations


def mouth_state(card_raw, **kwargs):
    """Both halves of one resolved mouth, for tests that assert on both."""
    from agent_core.skills.runtime import resolve_mouth

    mouth = resolve_mouth(card_raw, intent=kwargs.get("intent"), active_slug=kwargs.get("active_slug"))
    prompt = mouth.prompt()
    tools = mouth.tools(catalog_names=kwargs.get("catalog_names"), channel_tools=kwargs.get("channel_tools"))
    return {
        "card": mouth.card,
        "packs": list(mouth.packs),
        "allowed": set(tools.allowed) if tools.allowed is not None else None,
        "offered": list(tools.offered) if tools.offered is not None else None,
        "prefix": prompt.prefix,
        "active_slug": mouth.active_slug,
        "body_message": prompt.body_message,
    }
