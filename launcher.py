"""Interactive launcher for the AI Email Agent."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

console = Console()

# Module-level handle — only set when this launcher instance started the watcher.
# May be None if the watcher was started by a previous launcher session.
watcher_proc: subprocess.Popen | None = None  # type: ignore[type-arg]
_log_handle = None  # open file handle for watcher log (kept alive while proc runs)

LOG_PATH = Path("data/watcher.log")
PID_PATH = Path("data/watcher.pid")

# CREATE_NO_WINDOW: hide console window.
# CREATE_BREAKAWAY_FROM_JOB: detach from parent job object so the watcher
# survives after the launcher exits (required on modern Windows).
_WIN_FLAGS = subprocess.CREATE_NO_WINDOW | 0x01000000  # 0x01000000 = CREATE_BREAKAWAY_FROM_JOB


def _read_pid() -> int | None:
    try:
        return int(PID_PATH.read_text().strip())
    except (FileNotFoundError, ValueError):
        return None


def _is_pid_alive(pid: int) -> bool:
    """Return True if a process with this PID is still running."""
    if sys.platform == "win32":
        import ctypes
        PROCESS_QUERY_INFORMATION = 0x0400
        handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_INFORMATION, False, pid)
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def check_watcher() -> bool:
    """Return True if the watcher process is alive (this session or a previous one)."""
    global watcher_proc
    # Fast path: we have a live handle from this session.
    if watcher_proc is not None:
        if watcher_proc.poll() is None:
            return True
        watcher_proc = None

    # Slow path: check PID file left by a previous launcher session.
    pid = _read_pid()
    if pid is not None and _is_pid_alive(pid):
        return True

    # Stale PID file — clean it up.
    PID_PATH.unlink(missing_ok=True)
    return False


def start_watcher() -> None:
    global watcher_proc, _log_handle
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _log_handle = open(LOG_PATH, "w")  # noqa: SIM115
    flags = _WIN_FLAGS if sys.platform == "win32" else 0
    watcher_proc = subprocess.Popen(
        [sys.executable, "-m", "src.agent.watcher"],
        stdout=_log_handle,
        stderr=_log_handle,
        creationflags=flags,
    )
    PID_PATH.write_text(str(watcher_proc.pid))
    console.print(f"[green]Watcher started in background (logging to {LOG_PATH}).[/green]")


def stop_watcher() -> None:
    global watcher_proc, _log_handle
    stopped = False

    if watcher_proc is not None:
        watcher_proc.terminate()
        watcher_proc = None
        stopped = True
    else:
        # Watcher was started by a previous launcher session — kill by PID.
        pid = _read_pid()
        if pid is not None:
            try:
                os.kill(pid, signal.SIGTERM)
                stopped = True
            except OSError:
                pass

    if _log_handle is not None:
        _log_handle.close()
        _log_handle = None

    PID_PATH.unlink(missing_ok=True)

    if stopped:
        console.print("[yellow]Watcher stopped.[/yellow]")
    else:
        console.print("[dim]Watcher was not running.[/dim]")


def view_log(lines: int = 50) -> None:
    if not LOG_PATH.exists():
        console.print("[dim]No log file yet — start the watcher first.[/dim]")
        return
    all_lines = LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
    tail = all_lines[-lines:]
    console.print(f"\n[dim]--- last {len(tail)} lines of {LOG_PATH} ---[/dim]")
    for line in tail:
        console.print(line)
    console.print("[dim]--- end ---[/dim]")


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
            "  2. View watcher log\n"
            "  3. Backfill emails\n"
            "  4. Search emails\n"
            "  5. Topic status\n"
            "  6. Daily briefing\n"
            "  7. Reindex vector store\n"
            "  8. Edit config (.env)\n"
            "  9. Quit",
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
            view_log()
            input("\nPress Enter to return to menu...")

        elif choice == "3":
            days = prompt_with_default("Days to backfill", "30")
            run_command(["backfill", "--days", days])
            input("\nPress Enter to return to menu...")

        elif choice == "4":
            query = prompt_required("Search query")
            run_command(["search", query])
            input("\nPress Enter to return to menu...")

        elif choice == "5":
            topic = prompt_required("Topic")
            run_command(["status", topic])
            input("\nPress Enter to return to menu...")

        elif choice == "6":
            run_command(["briefing"])
            input("\nPress Enter to return to menu...")

        elif choice == "7":
            run_command(["reindex"])
            input("\nPress Enter to return to menu...")

        elif choice == "8":
            console.print("Opening .env in Notepad...")
            subprocess.run(["notepad", ".env"])

        elif choice == "9":
            console.print("[dim]Goodbye.[/dim]")
            break

        else:
            console.print("[red]Unknown option — try again.[/red]")


if __name__ == "__main__":
    main()
