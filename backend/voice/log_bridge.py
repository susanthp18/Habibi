"""Route standard-library logging into loguru.

Pipecat logs through loguru; everything the product owns (``agent_core.*``,
``voice.persist``, ``voice.crm_sink``) logs through the standard library. With
no bridge those are two independent systems, and only one of them is
configured.

The consequence, measured on call ``VS-6B252E0479``: the whole five-minute call
produced **zero** log lines from ``agent_core.understanding``,
``agent_core.turn_critic`` or ``voice.crm_sink``. The only product line that
surfaced at all was a bare ``WARNING:agent_core.tools.kb:…``, in stdlib's
default format, because ``WARNING`` is the root logger's default level and
anything below it was discarded before it reached a handler. Diagnosing an
agent whose analysis layer logs nothing is guesswork.

``install()`` replaces the root handlers with one that forwards every record to
loguru, preserving the original level, the originating module and any
exception info, so product and framework logs interleave in one stream at one
level.
"""

from __future__ import annotations

import inspect
import logging
import os

from loguru import logger

_DEFAULT_LEVEL = "INFO"


class InterceptHandler(logging.Handler):
    """Forward one stdlib record to loguru with its true call site."""

    def emit(self, record: logging.LogRecord) -> None:  # noqa: D102
        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # Walk out of the logging machinery so loguru reports the module that
        # actually logged, not this handler.
        frame, depth = inspect.currentframe(), 0
        while frame and (depth == 0 or frame.f_code.co_filename == logging.__file__):
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )


def install(level: str | None = None) -> None:
    """Bridge stdlib logging into loguru. Safe to call more than once.

    ``VOICE_LOG_LEVEL`` overrides the level; ``INFO`` by default, which is what
    makes the per-turn understanding, critic and CRM-sink lines visible.
    """
    resolved = (level or os.getenv("VOICE_LOG_LEVEL") or _DEFAULT_LEVEL).strip().upper()
    root = logging.getLogger()
    if not any(isinstance(h, InterceptHandler) for h in root.handlers):
        root.handlers = [InterceptHandler()]
    root.setLevel(resolved)

    # Third-party libraries that log per-request at INFO and would otherwise
    # bury the conversation. Their warnings still come through.
    for noisy in ("httpx", "httpcore", "urllib3", "azure", "aiortc", "aioice"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
