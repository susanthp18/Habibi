"""One helper for "the dict under this key, or an empty one".

``x.get(k) if isinstance(x.get(k), dict) else {}`` was written 68 times; it
reads the key twice and the type checker cannot narrow it.
"""

from __future__ import annotations

from typing import Any


def sub(container: Any, key: str) -> dict[str, Any]:
    """The mapping at ``container[key]`` when it is one, else ``{}``."""
    value = container.get(key) if isinstance(container, dict) else None
    return value if isinstance(value, dict) else {}
