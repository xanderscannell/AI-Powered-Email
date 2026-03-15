# Launcher Design — 2026-03-02

## Problem

Using the agent requires opening VS Code and running CLI commands manually. There is no single entry point to start the watcher or run common operations.

## Goal

A double-clickable `launch.bat` that activates the venv and opens an interactive menu for all common operations, including starting/stopping the long-running email watcher.

## Files

| File | Role |
|------|------|
| `launch.bat` | Double-click entry point (project root) |
| `launcher.py` | Rich menu loop with watcher process management (project root) |
| `src/agent/watcher.py` | Add `if __name__ == "__main__": main()` (one line) |

## `launch.bat`

~8 lines:
1. `cd /d "%~dp0"` — sets cwd to the script's directory regardless of launch context
2. Activate `.venv\Scripts\activate.bat`
3. `python launcher.py`
4. `pause` on exit/error so the terminal doesn't vanish

## Menu Layout

```
╔════════════════════════════════╗
║   AI Email Agent               ║
╠════════════════════════════════╣
║  1. Start watcher  [stopped]   ║
║  2. Backfill emails            ║
║  3. Search emails              ║
║  4. Topic status               ║
║  5. Daily briefing             ║
║  6. Reindex vector store       ║
║  7. Edit config (.env)         ║
║  8. Quit                       ║
╚════════════════════════════════╝
```

## Watcher Management (Option 1)

- `launcher.py` holds `watcher_proc: subprocess.Popen | None`
- Before each menu draw: `proc.poll()` — if the process has exited, clear the reference
- Status shown inline: `[stopped]` or `[running]`
- **Start**: `subprocess.Popen([sys.executable, "-m", "src.agent.watcher"], creationflags=CREATE_NEW_CONSOLE)` — watcher logs appear in a new console window
- **Stop** (when running): option text changes to "Stop watcher" — calls `proc.terminate()`
- **Quit with watcher running**: prompt "Watcher is still running — stop it? [Y/n]"

## CLI Commands

Commands run via `subprocess.run(["email-agent", ...])` against the venv-activated PATH.

| Option | Prompt before running | Command |
|--------|-----------------------|---------|
| Backfill | `Days to backfill [30]:` (default 30) | `email-agent backfill --days N` |
| Search | `Search query:` (required) | `email-agent search "..."` |
| Topic status | `Topic:` (required) | `email-agent status "..."` |
| Daily briefing | *(none)* | `email-agent briefing` |
| Reindex | *(none)* | `email-agent reindex` |

After each command completes, "Press Enter to return to menu."

## Config Editing (Option 7)

`subprocess.run(["notepad", ".env"])` — blocks until Notepad closes, then returns to menu. No parsing or in-memory editing.

## Dependencies

No new dependencies. Uses `rich` (already a project dep) for the menu header/border. Plain `input()` for prompts. `subprocess` from stdlib for running commands and the watcher.

## Out of Scope

- Web UI / TUI framework (textual)
- In-menu settings editor (inline toggles for .env values)
- Cross-platform support (Windows-only, `CREATE_NEW_CONSOLE` and `notepad`)
- Starting the watcher automatically on launch (explicit menu action instead)
