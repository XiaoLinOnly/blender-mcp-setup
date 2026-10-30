#!/usr/bin/env python3
"""Probe the Blender MCP server over stdio: initialize, tools/list, optional tools/call.

This checks the same path Qoder uses (uvx -> mcp-for-blender -> Blender socket)
without going through Qoder. Only the Python standard library is required.

Examples:
    python scripts/probe_blender_mcp.py
    python scripts/probe_blender_mcp.py --call get_scene_info
    python scripts/probe_blender_mcp.py --call execute_blender_code --args '{"code": "print(bpy.app.version_string)"}'
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time

DEFAULT_TIMEOUT = 90.0


class StdioMcpClient:
    def __init__(self, argv, env=None):
        self.proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            bufsize=0,
        )
        self.messages = queue.Queue()
        self.stderr_lines = []
        self.next_id = 0
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()

    def _read_stdout(self):
        for raw in iter(self.proc.stdout.readline, b""):
            line = raw.decode("utf-8", "replace").strip()
            if not line:
                continue
            try:
                self.messages.put(json.loads(line))
            except json.JSONDecodeError:
                self.stderr_lines.append("[non-json stdout] " + line[:300])
        self.messages.put(None)

    def _read_stderr(self):
        for raw in iter(self.proc.stderr.readline, b""):
            line = raw.decode("utf-8", "replace").rstrip()
            if line:
                self.stderr_lines.append(line)
                del self.stderr_lines[:-80]

    def _send(self, message):
        data = json.dumps(message, ensure_ascii=False).encode("utf-8")
        self.proc.stdin.write(data + b"\n")
        self.proc.stdin.flush()

    def notify(self, method, params=None):
        message = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        self._send(message)

    def request(self, method, params=None, timeout=DEFAULT_TIMEOUT):
        self.next_id += 1
        request_id = self.next_id
        message = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            message["params"] = params
        self._send(message)

        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("timed out waiting for %s (id=%d)" % (method, request_id))
            try:
                reply = self.messages.get(timeout=remaining)
            except queue.Empty:
                raise TimeoutError("timed out waiting for %s (id=%d)" % (method, request_id))
            if reply is None:
                raise RuntimeError("server closed stdout before replying to %s" % method)
            if reply.get("id") != request_id:
                continue
            if "error" in reply:
                raise RuntimeError("JSON-RPC error: " + json.dumps(reply["error"], ensure_ascii=False))
            return reply.get("result", {})

    def close(self):
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
        except OSError:
            pass
        try:
            self.proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(self.proc.pid)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
            else:
                self.proc.terminate()
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()


def find_uvx(explicit):
    if explicit:
        return explicit
    for name in ("uvx", "uvx.exe"):
        path = shutil.which(name)
        if path:
            return path
    fallback = os.path.join(os.path.expanduser("~"), ".local", "bin", "uvx.exe")
    if os.path.exists(fallback):
        return fallback
    raise SystemExit("uvx not found. Install uv first: https://docs.astral.sh/uv/")


def result_looks_like_error(result):
    """Blender MCP sometimes returns isError=false with an 'Error ...' text body."""
    if result.get("isError"):
        return True
    texts = [
        item.get("text", "")
        for item in result.get("content", [])
        if isinstance(item, dict) and item.get("type") == "text"
    ]
    return bool(texts) and all(text.strip().lower().startswith("error") for text in texts)


def summarize_result(result, full):
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if result_looks_like_error(result):
        text = "[looks like an error] " + text
    if not full and len(text) > 4000:
        text = text[:4000] + "\n... (truncated; use --full)"
    return text


def main():
    parser = argparse.ArgumentParser(description="Probe the Blender MCP stdio server")
    parser.add_argument("--uvx", help="Path to uvx.exe (default: search PATH and ~/.local/bin)")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help="Per-request timeout in seconds")
    parser.add_argument("--call", help="Tool name to call after tools/list")
    parser.add_argument("--args", default="{}", help="JSON object passed to --call (default: {})")
    parser.add_argument("--full", action="store_true", help="Do not truncate tool output")
    parser.add_argument("--verbose", action="store_true", help="Print server stderr on failure")
    args = parser.parse_args()

    uvx = find_uvx(args.uvx)
    client = StdioMcpClient([uvx, "mcp-for-blender"])
    ok = False
    try:
        init = client.request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "blender-mcp-probe", "version": "1.0"},
            },
            timeout=args.timeout,
        )
        client.notify("notifications/initialized")
        info = init.get("serverInfo", {})
        print("INIT: %s %s (protocol %s)" % (
            info.get("name", "?"), info.get("version", "?"), init.get("protocolVersion", "?")))

        listing = client.request("tools/list", {}, timeout=args.timeout)
        tools = listing.get("tools", [])
        print("TOOL COUNT: %d" % len(tools))
        names = [tool.get("name", "?") for tool in tools]
        print("TOOLS: " + ", ".join(names))

        if args.call:
            try:
                call_args = json.loads(args.args)
            except json.JSONDecodeError as exc:
                raise SystemExit("--args is not valid JSON: %s" % exc)
            if not isinstance(call_args, dict):
                raise SystemExit("--args must be a JSON object")
            result = client.request(
                "tools/call",
                {"name": args.call, "arguments": call_args},
                timeout=args.timeout,
            )
            print("CALL %s: %s" % (args.call, summarize_result(result, args.full)))
            ok = not result_looks_like_error(result)
        else:
            ok = len(tools) > 0
    except (RuntimeError, TimeoutError) as exc:
        print("ERROR: %s" % exc, file=sys.stderr)
        if args.verbose and client.stderr_lines:
            print("--- server stderr ---", file=sys.stderr)
            print("\n".join(client.stderr_lines[-30:]), file=sys.stderr)
        if "connect" in str(exc).lower() or "blender" in str(exc).lower():
            print("Hint: open Blender (GUI), enable the MCP addon, and check port 9876.", file=sys.stderr)
    finally:
        client.close()

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
