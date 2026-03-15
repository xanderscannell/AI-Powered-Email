# Launcher Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** A double-clickable `launch.bat` that activates the venv and opens a rich interactive menu for starting/stopping the watcher and running all CLI commands.

**Architecture:** `launch.bat` (8 lines, Windows) activates the venv and delegates to `launcher.py` (project root). `launcher.py` uses `rich` for the menu and `subprocess` for watcher process management and CLI command dispatch. The watcher runs in a separate console window; its liveness is tracked via `proc.poll()`.

**Tech Stack:** Python stdlib (`subprocess`, `sys`), `rich` (already a project dep), Windows `CREATE_NEW_CONSOLE` flag, Click CLI (`email-agent` script already installed).

---

### Task 1: Watcher `__main__` support

**Files:**
- Modify: `src/agent/watcher.py` (add 2 lines at end)
- Test: `tests/test_agent/test_watcher.py` (add 1 test)

**Step 1: Add the `__main__` block to `src/agent/watcher.py`**

Append to the very end of the file (after the `_amain` function):

```python
if __name__ == "__main__":
    main()
```

**Step 2: Add a test that `main` is importable and callable**

In `tests/test_agent/test_watcher.py`, add at the end of the file:

```python
def test_main_is_callable():
    from src.agent.watcher import main

    assert callable(main)
```

**Step 3: Run the test**

```
.venv/Scripts/pytest tests/test_agent/test_watcher.py::test_main_is_callable -v
```

Expected: PASS

**Step 4: Commit**

```
git add src/agent/watcher.py tests/test_agent/test_watcher.py
git commit -m "feat(watcher): support python -m src.agent.watcher invocation"
```

---

### Task 2: `launch.bat`

**Files:**
- Create: `launch.bat` (project root)

**Step 1: Create `launch.bat`**

```batch
@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\activate.bat" (
    echo ERROR: .venv not found. Run: uv sync
    pause
    exit /b 1
)
call .venv\Scripts\activate.bat
python launcher.py
if errorlevel 1 (
    echo.
    echo Launcher exited with an error.
    pause
)
```

**Step 2: Verify manually**

Double-click `launch.bat`. Expected: a terminal opens, venv activates, then Python fails with `ModuleNotFoundError: No module named 'launcher'` (because `launcher.py` doesn't exist yet). This confirms the bat is wired correctly.

**Step 3: Commit**

```
git add launch.bat
git commit -m "feat(launcher): add launch.bat entry point"
```

---

### Task 3: `launcher.py` — core implementation

**Files:**
- Create: `launcher.py` (project root)

**Step 1: Create `launcher.py`**

```python
"""Interactive launcher for the AI Email Agent."""

from __future__ import annotations

import subprocess
import sys

from rich.console import Console
from rich.panel import Panel

console = Console()

# Module-level — tracks the watcher subprocess across menu iterations.
watcher_proc: subprocess.Popen | None = None  # type: ignore[type-arg]


def check_watcher() -> bool:
    """Return True if the watcher process is alive; clear the ref if it has exited."""
    global watcher_proc
    if watcher_proc is not None and watcher_proc.poll() is not None:
        watcher_proc = None
    return watcher_proc is not None


def start_watcher() -> None:
    global watcher_proc
    flags = subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0
    watcher_proc = subprocess.Popen(
        [sys.executable, "-m", "src.agent.watcher"],
        creationflags=flags,
    )
    console.print("[green]Watcher started in a new window.[/green]")


def stop_watcher() -> None:
    global watcher_proc
    if watcher_proc is not None:
        watcher_proc.terminate()
        watcher_proc = None
    console.print("[yellow]Watcher stopped.[/yellow]")


def run_command(args: list[str]) -> None:
    """Run an email-agent sub-command in the current terminal."""
    subprocess.run(["email-agent", *args])


def prompt_required(label: str) -> str:
    """Prompt until the user enters a non-empty value."""
    while True:
        value = input(f"{label}: ").strip()
        if value:
            return value
        console.print("[red]Value required — try again.[/red]")


def prompt_with_default(label: str, default: str) -> str:
    value = input(f"{label} [{default}]: ").strip()
    return value if value else default


def print_menu() -> None:
    running = check_watcher()
    watcher_label = "Stop watcher" if running else "Start watcher"
    watcher_status = "  [green][running][/green]" if running else "[dim][stopped][/dim]"
    console.print(
        Panel(
            f"  1. {watcher_label} {watcher_status}\n"
            "  2. Backfill emails\n"
            "  3. Search emails\n"
            "  4. Topic status\n"
            "  5. Daily briefing\n"
            "  6. Reindex vector store\n"
            "  7. Edit config (.env)\n"
            "  8. Quit",
            title="[bold cyan]AI Email Agent[/bold cyan]",
            border_style="cyan",
            width=36,
        )
    )


def main() -> None:
    while True:
        console.print()
        print_menu()
        choice = input("Choice: ").strip()
        console.print()

        if choice == "1":
            if check_watcher():
                stop_watcher()
            else:
                start_watcher()

        elif choice == "2":
            days = prompt_with_default("Days to backfill", "30")
            run_command(["backfill", "--days", days])
            input("\nPress Enter to return to menu...")

        elif choice == "3":
            query = prompt_required("Search query")
            run_command(["search", query])
            input("\nPress Enter to return to menu...")

        elif choice == "4":
            topic = prompt_required("Topic")
            run_command(["status", topic])
            input("\nPress Enter to return to menu...")

        elif choice == "5":
            run_command(["briefing"])
            input("\nPress Enter to return to menu...")

        elif choice == "6":
            run_command(["reindex"])
            input("\nPress Enter to return to menu...")

        elif choice == "7":
            console.print("Opening .env in Notepad...")
            subprocess.run(["notepad", ".env"])

        elif choice == "8":
            if check_watcher():
                answer = input(
                    "Watcher is still running — stop it before quitting? [Y/n]: "
                ).strip().lower()
                if answer != "n":
                    stop_watcher()
            console.print("[dim]Goodbye.[/dim]")
            break

        else:
            console.print("[red]Unknown option — try again.[/red]")


if __name__ == "__main__":
    main()
```

**Step 2: Verify manually**

Double-click `launch.bat`. Expected: menu appears. Test:
- Press 8 → "Goodbye." → terminal closes (or stays open due to bat's `pause`)
- Press 1 → watcher window opens with Gmail MCP connection attempt
- Press 3 → prompts "Search query:", runs `email-agent search`, returns to menu on Enter
- Press 7 → Notepad opens with `.env` contents

**Step 3: Commit**

```
git add launcher.py
git commit -m "feat(launcher): add interactive menu launcher"
```

---

### Task 4: Tests for `launcher.py`

**Files:**
- Create: `tests/test_launcher.py`

**Step 1: Write the tests**

```python
"""Tests for launcher.py — watcher process state management."""

from unittest.mock import MagicMock

import pytest


@pytest.fixture(autouse=True)
def reset_watcher_proc():
    """Reset module-level watcher_proc between tests."""
    import launcher

    launcher.watcher_proc = None
    yield
    launcher.watcher_proc = None


def test_check_watcher_false_when_no_proc():
    import launcher

    assert launcher.check_watcher() is False


def test_check_watcher_true_when_proc_running():
    import launcher

    mock_proc = MagicMock()
    mock_proc.poll.return_value = None  # still running
    launcher.watcher_proc = mock_proc

    assert launcher.check_watcher() is True


def test_check_watcher_clears_exited_proc():
    import launcher

    mock_proc = MagicMock()
    mock_proc.poll.return_value = 0  # exited
    launcher.watcher_proc = mock_proc

    assert launcher.check_watcher() is False
    assert launcher.watcher_proc is None


def test_stop_watcher_terminates_proc():
    import launcher

    mock_proc = MagicMock()
    mock_proc.poll.return_value = None
    launcher.watcher_proc = mock_proc

    launcher.stop_watcher()

    mock_proc.terminate.assert_called_once()
    assert launcher.watcher_proc is None


def test_prompt_with_default_uses_default_on_empty(monkeypatch):
    import launcher

    monkeypatch.setattr("builtins.input", lambda _: "")
    result = launcher.prompt_with_default("Label", "30")
    assert result == "30"


def test_prompt_with_default_uses_user_value(monkeypatch):
    import launcher

    monkeypatch.setattr("builtins.input", lambda _: "7")
    result = launcher.prompt_with_default("Label", "30")
    assert result == "7"
```

**Step 2: Run the tests**

```
.venv/Scripts/pytest tests/test_launcher.py -v
```

Expected: 6 tests PASS

**Step 3: Run full test suite to confirm no regressions**

```
.venv/Scripts/pytest --tb=short
```

Expected: all 252 + new tests PASS

**Step 4: Commit**

```
git add tests/test_launcher.py
git commit -m "test(launcher): add watcher state management tests"
```

---

## Done

The system is now launchable by double-clicking `launch.bat`. The watcher can be started and stopped from the menu, and all CLI commands are accessible without opening VS Code.
