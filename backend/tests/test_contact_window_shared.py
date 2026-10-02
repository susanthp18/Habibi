"""``contact_window`` is the one owner of the default contact window.

Two copies of the rule once disagreed (10:00-19:00 against 09:00-20:00 IST), so
a promise date's verdict depended on which entry point checked it. Every reader
now calls this module, which must stay importable without ``db``.
"""

from __future__ import annotations

import contact_window


def test_default_bounds() -> None:
    assert contact_window.DEFAULT_START_HOUR == 9
    assert contact_window.DEFAULT_END_HOUR == 20
    assert contact_window.DEFAULT_WINDOW == "09:00-20:00 IST"


def test_contact_window_is_a_leaf_module() -> None:
    """It is importable without ``db``; that is the whole point of the split."""
    import subprocess
    import sys

    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import contact_window; "
            "assert 'db' not in sys.modules; "
            "assert 'sqlalchemy' not in sys.modules; "
            "print(contact_window.DEFAULT_WINDOW)",
        ],
        capture_output=True,
        text=True,
        cwd=str(__import__("pathlib").Path(__file__).resolve().parents[1]),
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == contact_window.DEFAULT_WINDOW
