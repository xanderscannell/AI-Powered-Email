"""Custom stdio transport for MCP — works around Windows/Git Bash subprocess issues.

The upstream ``mcp.client.stdio.stdio_client`` uses ``anyio.open_process()``,
which relies on asyncio's ProactorEventLoop IOCP pipe handling.  Under
Git Bash / mintty on Windows this frequently fails with "Connection closed"
during the MCP handshake, even though raw ``subprocess.Popen`` I/O works fine.

This module provides a drop-in ``stdio_client()`` replacement that:

1. Spawns the MCP server with plain ``subprocess.Popen`` (always works).
2. Bridges sync pipe I/O to anyio memory-object streams via an asyncio queue.
3. Yields the exact ``(read_stream, write_stream)`` pair that ``ClientSession``
   expects, so callers don't need any changes.
"""

import asyncio
import logging
import os
import subprocess
import sys
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TextIO

import anyio
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from mcp import types
from mcp.client.stdio import StdioServerParameters, get_default_environment
from mcp.shared.session import SessionMessage

logger = logging.getLogger(__name__)


def _get_executable_command(command: str) -> str:
    """Resolve the command for the current platform."""
    if sys.platform == "win32":
        import shutil
        resolved = shutil.which(command)
        if resolved:
            return resolved
    return command


@asynccontextmanager
async def stdio_client(
    server: StdioServerParameters,
    errlog: TextIO = sys.stderr,
) -> AsyncIterator[
    tuple[
        MemoryObjectReceiveStream[SessionMessage | Exception],
        MemoryObjectSendStream[SessionMessage],
    ]
]:
    """Drop-in replacement for ``mcp.client.stdio.stdio_client``.

    Uses ``subprocess.Popen`` + threads instead of ``anyio.open_process``
    to avoid Windows IOCP pipe bugs under Git Bash / mintty.
    """
    read_stream_writer, read_stream = anyio.create_memory_object_stream[
        SessionMessage | Exception
    ](32)
    write_stream, write_stream_reader = anyio.create_memory_object_stream[
        SessionMessage
    ](32)

    command = _get_executable_command(server.command)
    env = (
        {**get_default_environment(), **server.env}
        if server.env is not None
        else get_default_environment()
    )

    logger.info("Spawning MCP server: %s %s", command, server.args)
    proc = subprocess.Popen(
        [command, *server.args],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=errlog,
        env=env,
        cwd=server.cwd,
    )
    logger.info("MCP server process started (pid=%d)", proc.pid)

    loop = asyncio.get_running_loop()
    stop = threading.Event()

    # -- Inbound: subprocess stdout → anyio read_stream -------------------------

    def _stdout_reader() -> None:
        """Sync thread: reads JSON-RPC lines from stdout, pushes to async queue."""
        assert proc.stdout is not None
        logger.debug("stdout reader thread started")
        try:
            while not stop.is_set():
                line_bytes = proc.stdout.readline()
                if not line_bytes:
                    logger.warning("MCP server stdout closed (EOF)")
                    break
                line = line_bytes.decode(
                    server.encoding, errors=server.encoding_error_handler
                ).strip()
                if not line:
                    continue
                try:
                    message = types.JSONRPCMessage.model_validate_json(line)
                    session_message = SessionMessage(message)
                    logger.debug("stdout reader: forwarding JSON-RPC message")
                    asyncio.run_coroutine_threadsafe(
                        read_stream_writer.send(session_message), loop
                    ).result(timeout=10)
                except Exception as exc:
                    logger.warning("Failed to parse JSON-RPC line: %.200s", line)
                    logger.exception("Parse error details")
                    try:
                        asyncio.run_coroutine_threadsafe(
                            read_stream_writer.send(exc), loop
                        ).result(timeout=10)
                    except Exception:
                        pass
        except Exception:
            if not stop.is_set():
                logger.exception("stdout reader thread crashed")

    # -- Outbound: anyio write_stream → subprocess stdin ------------------------

    async def _stdin_writer() -> None:
        """Async task: reads SessionMessages from write_stream, writes to stdin."""
        assert proc.stdin is not None
        try:
            async with write_stream_reader:
                async for session_message in write_stream_reader:
                    json_str = session_message.message.model_dump_json(
                        by_alias=True, exclude_none=True
                    )
                    data = (json_str + "\n").encode(
                        encoding=server.encoding,
                        errors=server.encoding_error_handler,
                    )
                    # Write to stdin from a thread to avoid blocking the event loop
                    await loop.run_in_executor(None, proc.stdin.write, data)
                    await loop.run_in_executor(None, proc.stdin.flush)
        except anyio.ClosedResourceError:
            pass
        except Exception:
            if not stop.is_set():
                logger.exception("stdin writer task crashed")

    reader_thread = threading.Thread(
        target=_stdout_reader, daemon=True, name="mcp-stdout-reader"
    )
    reader_thread.start()

    async with anyio.create_task_group() as tg:
        tg.start_soon(_stdin_writer)
        try:
            yield read_stream, write_stream
        finally:
            stop.set()

            if proc.stdin:
                try:
                    proc.stdin.close()
                except Exception:
                    pass

            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)

            await read_stream.aclose()
            await write_stream.aclose()
            await read_stream_writer.aclose()
            tg.cancel_scope.cancel()
