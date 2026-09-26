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

from typing import Any
import inspect
import logging
import os
import sys

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

        # The message is already scrubbed -- observability.RedactingFilter is
        # attached to this handler in install() and rewrites record.msg before
        # emit runs. The traceback is not: loguru renders record.exc_info
        # itself, and a traceback carries the arguments that raised, so
        # "ValueError: 9876543210 is not a valid amount" is a phone number in a
        # log line. Render it here, through the scrubber, and hand loguru text.
        message = record.getMessage()
        if record.exc_info:
            from observability import RedactingTextFormatter

            message = f"{message}\n{RedactingTextFormatter().formatException(record.exc_info)}"
        logger.opt(depth=depth).log(level, message)


def _scrub_loguru_message(record: Any) -> None:
    """Mask PII in every loguru message, including Pipecat's own.

    Never raises: a scrubber that takes down the logger is worse than the leak
    it prevents, and the withheld-text fallback is the same one the stdlib side
    uses.

    Residual, stated rather than hidden: loguru renders ``record["exception"]``
    with its own formatter, which this does not reach. Tracebacks raised inside
    Pipecat are therefore still unscrubbed. Everything the product logs comes
    through ``InterceptHandler``, which renders its own scrubbed traceback above.
    """
    from observability import _redact_or_withhold

    message = record.get("message")
    if isinstance(message, str):
        record["message"] = _redact_or_withhold(message)


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

    # Loguru's built-in stderr sink accepts DEBUG independently of the stdlib
    # root level. Pipecat logs the entire model context at DEBUG, including
    # borrower facts. Replace only that built-in sink; leave a caller's custom
    # sink (for example, a test capture) alone. A second install has no sink 0.
    try:
        logger.remove(0)
    except ValueError:
        pass
    else:
        logger.add(sys.stderr, level=resolved, backtrace=False, diagnose=False)

    # Redaction, on both halves of the stream.
    #
    # The stdlib half goes through the filter, same as the API's handlers. The
    # loguru half does not touch stdlib at all -- Pipecat logs straight to
    # loguru -- so a filter cannot see it, and this path had no scrubbing of any
    # kind. A patcher is loguru's supported way in: configure(patcher=...)
    # leaves existing sinks alone and rewrites every message before it is
    # formatted, whoever logged it.
    from observability import attach_redactor

    for handler in root.handlers:
        if isinstance(handler, InterceptHandler):
            attach_redactor(handler)
    logger.configure(patcher=_scrub_loguru_message)

    # Third-party libraries that log per-request at INFO and would otherwise
    # bury the conversation. Their warnings still come through.
    for noisy in ("httpx", "httpcore", "urllib3", "azure", "aiortc", "aioice"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
