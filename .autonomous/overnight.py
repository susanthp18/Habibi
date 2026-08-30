import json
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path


# ============================================================
# CONFIGURATION
# ============================================================

ROOT = Path(__file__).resolve().parent.parent
AUTO = ROOT / ".autonomous"
LOG_DIR = AUTO / "logs"

STATE_FILE = AUTO / "state.json"
BACKLOG_FILE = AUTO / "backlog.json"

CLAUDE_PROMPT = AUTO / "claude_prompt.md"
CURSOR_PROMPT = AUTO / "cursor_prompt.md"
RULES_FILE = AUTO / "rules.md"


# Your exact models
CLAUDE_MODEL = "opus"
CLAUDE_EFFORT = "high"

CURSOR_MODEL = "cursor-grok-4.6-high"


# Start with 1.
# Change to None for unlimited operation.
MAX_CYCLES = 1

# Maximum attempts to repair a failing cycle
MAX_REPAIR_ATTEMPTS = 2

# Wait between cycles
SLEEP_SECONDS = 10

# Agent timeouts
CLAUDE_TIMEOUT = 60 * 60
CURSOR_TIMEOUT = 45 * 60


# ============================================================
# UTILITIES
# ============================================================

def now():
    return datetime.now().isoformat(timespec="seconds")


def ensure_files():

    LOG_DIR.mkdir(parents=True, exist_ok=True)

    if not STATE_FILE.exists():
        STATE_FILE.write_text(
            json.dumps({
                "cycle": 0,
                "successful_cycles": 0,
                "failed_cycles": 0,
                "blocked_cycles": 0,
                "consecutive_failures": 0,
                "started_at": None,
                "last_cycle_at": None,
                "last_status": "not_started",
                "last_task": None
            }, indent=2),
            encoding="utf-8"
        )

    if not BACKLOG_FILE.exists():
        BACKLOG_FILE.write_text(
            json.dumps({
                "tasks": [],
                "blocked": [],
                "completed": []
            }, indent=2),
            encoding="utf-8"
        )


def load_json(path):

    return json.loads(
        path.read_text(encoding="utf-8")
    )


def save_json(path, data):

    path.write_text(
        json.dumps(data, indent=2),
        encoding="utf-8"
    )


def log(cycle, name, text):

    path = LOG_DIR / f"cycle_{cycle:04d}_{name}.log"

    path.write_text(
        text,
        encoding="utf-8"
    )

    return path


# ============================================================
# COMMAND EXECUTION
# ============================================================

def execute(
    command,
    timeout,
    cycle,
    log_name
):

    print()
    print("=" * 80)
    print("COMMAND:")
    print(" ".join(command))
    print("=" * 80)

    try:

        process = subprocess.run(
            command,
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=timeout
        )

        output = (
            process.stdout
            + "\n\n--- STDERR ---\n\n"
            + process.stderr
        )

        print(output)

        log(
            cycle,
            log_name,
            output
        )

        return process.returncode, output

    except subprocess.TimeoutExpired as e:

        output = (
            f"TIMEOUT after {timeout} seconds\n\n"
            f"STDOUT:\n{e.stdout}\n\n"
            f"STDERR:\n{e.stderr}"
        )

        print(output)

        log(
            cycle,
            log_name,
            output
        )

        return -1, output

    except Exception as e:

        output = f"EXECUTION ERROR:\n{repr(e)}"

        print(output)

        log(
            cycle,
            log_name,
            output
        )

        return -1, output


# ============================================================
# GIT
# ============================================================

def git_status(cycle):

    return execute(
        ["git", "status", "--short"],
        60,
        cycle,
        "git_status"
    )


def git_diff(cycle):

    return execute(
        ["git", "diff", "--stat"],
        60,
        cycle,
        "git_diff"
    )


def git_log(cycle):

    return execute(
        [
            "git",
            "log",
            "--oneline",
            "-10"
        ],
        60,
        cycle,
        "git_log"
    )


def git_commit(cycle):

    return execute(
        [
            "git",
            "add",
            "."
        ],
        60,
        cycle,
        "git_add"
    )[0] == 0 and execute(
        [
            "git",
            "commit",
            "-m",
            f"autonomous: verified cycle {cycle}"
        ],
        120,
        cycle,
        "git_commit"
    )[0] == 0


# ============================================================
# TEST DISCOVERY
# ============================================================

def run_tests(cycle):

    results = []

    # Python
    if (
        (ROOT / "pytest.ini").exists()
        or (ROOT / "pyproject.toml").exists()
        or (ROOT / "tests").exists()
    ):

        code, output = execute(
            ["python", "-m", "pytest"],
            30 * 60,
            cycle,
            "pytest"
        )

        results.append({
            "test": "pytest",
            "passed": code == 0
        })

        if code != 0:
            return False, results

    # Node / frontend
    package_json = ROOT / "package.json"

    if package_json.exists():

        package = json.loads(
            package_json.read_text(
                encoding="utf-8"
            )
        )

        scripts = package.get(
            "scripts",
            {}
        )

        if "lint" in scripts:

            code, output = execute(
                ["npm", "run", "lint"],
                20 * 60,
                cycle,
                "npm_lint"
            )

            results.append({
                "test": "npm run lint",
                "passed": code == 0
            })

            if code != 0:
                return False, results

        if "build" in scripts:

            code, output = execute(
                ["npm", "run", "build"],
                30 * 60,
                cycle,
                "npm_build"
            )

            results.append({
                "test": "npm run build",
                "passed": code == 0
            })

            if code != 0:
                return False, results

    return True, results


# ============================================================
# CLAUDE
# ============================================================

def run_claude(cycle, extra_instruction=""):

    prompt = CLAUDE_PROMPT.read_text(
        encoding="utf-8"
    )

    rules = RULES_FILE.read_text(
        encoding="utf-8"
    )

    full_prompt = f"""
{rules}

============================================================

{prompt}

============================================================

AUTONOMOUS SUPERVISOR INSTRUCTION

Cycle: {cycle}

{extra_instruction}

You have authority to inspect and modify the repository.

Do not merely explain what should be done.

Actually implement the highest-value improvement.

Begin now.
"""

    return execute(
        [
            "claude",
            "--model",
            CLAUDE_MODEL,
            "--effort",
            CLAUDE_EFFORT,
            "--permission-mode",
            "bypassPermissions",
            "-p",
            full_prompt
        ],
        CLAUDE_TIMEOUT,
        cycle,
        "claude"
    )


# ============================================================
# CURSOR / GROK
# ============================================================

def run_cursor(cycle):

    prompt = CURSOR_PROMPT.read_text(
        encoding="utf-8"
    )

    return execute(
        [
            "cursor-agent",
            "--model",
            CURSOR_MODEL,
            "--print",
            "--force",
            "--trust",
            prompt
        ],
        CURSOR_TIMEOUT,
        cycle,
        "cursor"
    )


# ============================================================
# MAIN CYCLE
# ============================================================

def run_cycle(state):

    cycle = state["cycle"]

    print()
    print()
    print("#" * 80)
    print(f"              AUTONOMOUS CYCLE {cycle}")
    print("#" * 80)

    # --------------------------------------------------------
    # INITIAL STATE
    # --------------------------------------------------------

    git_status(cycle)
    git_log(cycle)
    git_diff(cycle)

    # --------------------------------------------------------
    # CLAUDE IMPLEMENTATION
    # --------------------------------------------------------

    code, output = run_claude(
        cycle,
        """
Select the highest-value safe improvement you can identify.

Prioritize real bugs, incomplete functionality, integration problems,
test gaps, reliability issues, and user-facing problems.

Complete the implementation and verify it.
"""
    )

    if code != 0:

        print("Claude failed.")

        state["failed_cycles"] += 1
        state["consecutive_failures"] += 1
        state["last_status"] = "claude_failed"

        return False

    # --------------------------------------------------------
    # FIRST TEST
    # --------------------------------------------------------

    passed, results = run_tests(cycle)

    if not passed:

        print()
        print("Initial verification FAILED.")
        print("Sending failure back to Claude.")

        for attempt in range(
            1,
            MAX_REPAIR_ATTEMPTS + 1
        ):

            code, output = run_claude(
                cycle,
                f"""
This is repair attempt {attempt}.

The automated verification has failed.

Inspect the test output saved in:

.autonomous/logs/

Find the ROOT CAUSE.

Fix the problem.

Do not weaken or delete tests.

After fixing, run the failing tests and broader verification.
"""
            )

            if code != 0:
                continue

            passed, results = run_tests(
                cycle
            )

            if passed:
                break

        if not passed:

            print(
                "Claude could not restore verification."
            )

            state["failed_cycles"] += 1
            state["consecutive_failures"] += 1
            state["last_status"] = "tests_failed"

            return False

    # --------------------------------------------------------
    # INDEPENDENT GROK REVIEW
    # --------------------------------------------------------

    print()
    print("Running independent Cursor/Grok review...")

    code, output = run_cursor(cycle)

    if code != 0:

        print(
            "Cursor/Grok review failed."
        )

        state["failed_cycles"] += 1
        state["consecutive_failures"] += 1
        state["last_status"] = "cursor_failed"

        return False

    # --------------------------------------------------------
    # FINAL VERIFICATION
    # --------------------------------------------------------

    print()
    print("Running FINAL verification...")

    passed, results = run_tests(cycle)

    if not passed:

        print(
            "Cursor introduced or exposed a problem."
        )

        # Give Claude one final repair opportunity.

        code, output = run_claude(
            cycle,
            """
The independent review was completed, but final verification is failing.

Inspect:

.autonomous/logs/

Determine whether the failure was caused by the current cycle.

Fix the root cause.

Run the complete relevant verification again.

Do not weaken tests.
"""
        )

        if code == 0:
            passed, results = run_tests(
                cycle
            )

    # --------------------------------------------------------
    # FINAL DECISION
    # --------------------------------------------------------

    if passed:

        print()
        print("=" * 80)
        print("FINAL VERIFICATION PASSED")
        print("=" * 80)

        git_diff(cycle)

        committed = git_commit(cycle)

        if committed:

            print(
                f"Cycle {cycle} committed successfully."
            )

            state["successful_cycles"] += 1
            state["consecutive_failures"] = 0
            state["last_status"] = "success"

            return True

        print(
            "Verification passed but Git commit failed."
        )

        state["failed_cycles"] += 1
        state["consecutive_failures"] += 1
        state["last_status"] = "commit_failed"

        return False

    else:

        print()
        print("=" * 80)
        print("FINAL VERIFICATION FAILED")
        print("=" * 80)

        state["failed_cycles"] += 1
        state["consecutive_failures"] += 1
        state["last_status"] = "verification_failed"

        return False


# ============================================================
# SUPERVISOR
# ============================================================

def main():

    ensure_files()

    state = load_json(
        STATE_FILE
    )

    if state["started_at"] is None:
        state["started_at"] = now()

    print()
    print("=" * 80)
    print("       AUTONOMOUS SOFTWARE DEVELOPMENT SYSTEM")
    print("=" * 80)
    print()
    print("Claude : Opus / HIGH")
    print("Cursor : Grok 4.6 HIGH")
    print()
    print(f"Project: {ROOT}")
    print()

    while True:

        if (
            MAX_CYCLES is not None
            and state["cycle"] >= MAX_CYCLES
        ):
            print()
            print(
                "Maximum cycle count reached."
            )
            break

        # ----------------------------------------------------
        # SAFETY: TOO MANY CONSECUTIVE FAILURES
        # ----------------------------------------------------

        if state["consecutive_failures"] >= 5:

            print()
            print("=" * 80)
            print(
                "5 CONSECUTIVE FAILURES."
            )
            print(
                "PAUSING TO PREVENT AN AUTONOMOUS FAILURE LOOP."
            )
            print("=" * 80)

            state["last_status"] = (
                "paused_after_consecutive_failures"
            )

            save_json(
                STATE_FILE,
                state
            )

            break

        # ----------------------------------------------------
        # NEXT CYCLE
        # ----------------------------------------------------

        state["cycle"] += 1
        state["last_cycle_at"] = now()

        save_json(
            STATE_FILE,
            state
        )

        success = run_cycle(
            state
        )

        save_json(
            STATE_FILE,
            state
        )

        # ----------------------------------------------------
        # CONTINUE
        # ----------------------------------------------------

        print()
        print(
            f"Cycle {state['cycle']} finished."
        )

        print(
            f"Successes: {state['successful_cycles']}"
        )

        print(
            f"Failures: {state['failed_cycles']}"
        )

        print(
            f"Consecutive failures: "
            f"{state['consecutive_failures']}"
        )

        print()
        print(
            f"Waiting {SLEEP_SECONDS} seconds..."
        )

        time.sleep(
            SLEEP_SECONDS
        )


if __name__ == "__main__":
    main()