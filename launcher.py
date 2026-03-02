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
