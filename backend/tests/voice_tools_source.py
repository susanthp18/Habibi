"""The voice tool set as one text, for the tests that still read it as source.

``voice/tools.py`` became ``voice/tools.py`` + ``voice/tools_scope.py`` + one
module per handler section (``voice/tools_identity.py`` ...). A pin that read
``inspect.getsource(voice.tools)`` reads the whole set through this instead;
converting those pins to behaviour is the ratchet's job, one at a time.
"""

from __future__ import annotations

import inspect


def source() -> str:
    from voice import (
        tools,
        tools_closing,
        tools_handoff,
        tools_identity,
        tools_knowledge,
        tools_negotiate,
        tools_offers,
        tools_position,
        tools_scope,
    )

    return "\n".join(
        inspect.getsource(m)
        for m in (
            tools,
            tools_scope,
            tools_identity,
            tools_offers,
            tools_position,
            tools_negotiate,
            tools_knowledge,
            tools_closing,
            tools_handoff,
        )
    )


def handlers_source() -> str:
    """``voice/bot_handlers.py`` plus its sections, the same way."""
    from voice import (
        bot_handlers,
        bot_handlers_connect,
        bot_handlers_idle,
        bot_handlers_scope,
        bot_handlers_teardown,
        bot_handlers_turns,
        bot_handlers_watchdogs,
    )

    return "\n".join(
        inspect.getsource(m)
        for m in (
            bot_handlers,
            bot_handlers_scope,
            bot_handlers_idle,
            bot_handlers_turns,
            bot_handlers_watchdogs,
            bot_handlers_connect,
            bot_handlers_teardown,
        )
    )
