"""Claude subscription mode: decisions come from the local Claude Code CLI.

Each decision runs ``claude -p`` (print mode) on the machine hosting the
backend, so it uses whatever account that CLI is logged in to (a Pro/Max
subscription). Nothing is billed per token by this app.

* Sessions: with ``session_mode="per_agent"`` every agent has its own Claude
  Code conversation (a fixed UUID per world and agent). The first decision
  starts it with ``--session-id``; later ones continue it with ``--resume``, so
  the model also remembers its earlier decisions. ``"fresh"`` runs every
  decision as a new, unsaved conversation (``--no-session-persistence``).
* Safety: other agents' messages end up in the prompt, so the CLI runs with
  every tool disabled (``--tools ""``), no MCP servers, in an empty working
  directory. API-key variables are removed from its environment so the CLI
  uses the subscription login rather than billing an API key.
* Compatibility: flags are only passed if ``claude --help`` lists them, so
  older CLI versions degrade (e.g. without ``--json-schema`` the JSON reply is
  parsed from the text).

Only environment variables (never the HTTP API) choose which executable runs:
``AISIM_CLAUDE_PATH`` (default: ``claude`` on PATH), ``AISIM_CLAUDE_WORKDIR``
(default: ``~/.cache/aisim/claude-code``) and ``AISIM_CLAUDE_EXTRA_ARGS``.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shlex
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

from .base import LLMError, LLMRequest, LLMResponse

# Removed from the CLI's environment so it authenticates with the subscription.
# (CLAUDE_CODE_OAUTH_TOKEN from `claude setup-token` is a subscription login and is kept.)
_STRIPPED_ENV = ("ANTHROPIC_API_KEY", "ANTHROPIC_API_TOKEN", "ANTHROPIC_AUTH_TOKEN", "CLAUDECODE")
_SESSION_NAMESPACE = uuid.UUID("6f1d3c52-8a1e-4c55-9a43-1f0c2b7e9d10")
_FALLBACK_DISALLOWED = ["Bash", "Edit", "Write", "MultiEdit", "NotebookEdit", "Read", "Glob", "Grep", "WebFetch",
                        "WebSearch", "Task", "Agent", "TodoWrite"]

_help_cache: dict[str, set[str]] = {}


def find_cli() -> str | None:
    configured = os.path.expanduser(os.environ.get("AISIM_CLAUDE_PATH", "").strip())
    if configured:
        return configured if (shutil.which(configured) or Path(configured).is_file()) else None
    return shutil.which("claude")


async def _supported_flags(exe: str) -> set[str]:
    if exe not in _help_cache:
        flags: set[str] = set()
        try:
            proc = await asyncio.create_subprocess_exec(
                exe, "--help", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=20)
            flags = set(re.findall(r"(--[a-z][a-z0-9-]*)", out.decode(errors="replace")))
        except (OSError, asyncio.TimeoutError):
            pass
        _help_cache[exe] = flags
    return _help_cache[exe]


def session_uuid(world_id: str, agent_id: str) -> str:
    return str(uuid.uuid5(_SESSION_NAMESPACE, f"{world_id}:{agent_id}"))


def _classify(text: str) -> tuple[str, bool]:
    t = text.lower()
    if "unknown option" in t or "unknown argument" in t:
        return "cli_unsupported_option", False
    if any(s in t for s in ("not logged in", "/login", "invalid api key", "authentication", "oauth")):
        return "authentication", False
    if any(s in t for s in ("usage limit", "rate limit", "limit reached", "overloaded")):
        return "rate_limited", True
    if "already in use" in t or "already exists" in t:
        return "session_exists", False
    if "no conversation found" in t or "session not found" in t or "no session" in t:
        return "session_missing", False
    return "cli_error", True


class ClaudeCodeProvider:
    name = "claude_code"

    def __init__(self, model: str, world_id: str, timeout_seconds: float = 120.0, effort: str | None = None,
                 session_mode: str = "per_agent", executable: str | None = None, workdir: str | Path | None = None):
        self.model = model
        self.world_id = world_id or "default"
        self.timeout_seconds = timeout_seconds
        self.effort = effort
        self.session_mode = session_mode
        self.executable = executable or find_cli()
        base = Path(workdir or os.environ.get("AISIM_CLAUDE_WORKDIR") or Path.home() / ".cache" / "aisim" / "claude-code"
                    ).expanduser()
        # One empty directory per world: sessions are stored per working directory,
        # and nothing in it (no CLAUDE.md, no settings) leaks into the prompt.
        self.workdir = base / re.sub(r"[^A-Za-z0-9_-]", "_", self.world_id)
        self.extra_args = shlex.split(os.environ.get("AISIM_CLAUDE_EXTRA_ARGS", ""))
        self._started: set[str] = set()

    def _env(self) -> dict[str, str]:
        env = {k: v for k, v in os.environ.items() if k not in _STRIPPED_ENV}
        env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"
        return env

    def _command(self, request: LLMRequest, flags: set[str], session: list[str]) -> list[str]:
        assert self.executable
        cmd = [self.executable, "-p", "--output-format", "json"]
        if self.model:
            cmd += ["--model", self.model]
        if "--system-prompt" in flags:
            cmd += ["--system-prompt", request.system]
        if "--json-schema" in flags:
            cmd += ["--json-schema", json.dumps(request.json_schema)]
        if "--tools" in flags:
            cmd += ["--tools", ""]
        else:
            cmd += ["--disallowedTools", *_FALLBACK_DISALLOWED]
        if "--strict-mcp-config" in flags:
            cmd.append("--strict-mcp-config")
        if self.effort and "--effort" in flags:
            cmd += ["--effort", self.effort]
        return cmd + session + self.extra_args

    def _user_text(self, request: LLMRequest, flags: set[str]) -> str:
        if "--system-prompt" in flags:
            return request.user
        # Very old CLIs: no custom system prompt, so send the rules with the message.
        return f"{request.system}\n\n---\n\n{request.user}"

    async def _run(self, cmd: list[str], stdin: str) -> tuple[int, str, str]:
        self.workdir.mkdir(parents=True, exist_ok=True)
        proc = await asyncio.create_subprocess_exec(
            *cmd, cwd=str(self.workdir), env=self._env(), stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            out, err = await asyncio.wait_for(proc.communicate(stdin.encode()), timeout=self.timeout_seconds)
        except asyncio.TimeoutError as exc:
            raise LLMError("timeout", f"claude CLI did not answer within {self.timeout_seconds:.0f}s",
                           retryable=True) from exc
        finally:
            # Also runs when the decision window cancels this call: never leave a CLI running.
            if proc.returncode is None:
                proc.kill()
                await proc.wait()
        return proc.returncode or 0, out.decode(errors="replace"), err.decode(errors="replace")

    async def complete(self, request: LLMRequest) -> LLMResponse:
        if not self.executable:
            raise LLMError("cli_not_found", "the 'claude' command was not found on the server "
                                            "(install Claude Code or set AISIM_CLAUDE_PATH)")
        flags = await _supported_flags(self.executable)
        agent_id = str(request.metadata.get("agent_id") or "agent")
        sid = session_uuid(self.world_id, agent_id)
        t0 = time.monotonic()
        for _ in range(2):  # at most one retry, to switch between --session-id and --resume
            if self.session_mode != "per_agent":
                session = ["--no-session-persistence"] if "--no-session-persistence" in flags else []
            elif sid in self._started:
                session = ["--resume", sid]
            else:
                session = ["--session-id", sid]
            code, out, err = await self._run(self._command(request, flags, session), self._user_text(request, flags))
            try:
                return self._parse(code, out, err, t0, sid)
            except LLMError as exc:
                if exc.kind == "session_exists":
                    self._started.add(sid)
                    continue
                if exc.kind == "session_missing":
                    self._started.discard(sid)
                    continue
                raise
        raise LLMError("cli_error", "could not start or resume the agent's Claude Code session")

    def _parse(self, code: int, out: str, err: str, t0: float, sid: str) -> LLMResponse:
        envelope: dict[str, Any] | None = None
        text = out.strip()
        if text:
            # The JSON result is the last line that parses (older CLIs may print warnings first).
            for line in reversed(text.splitlines()):
                try:
                    candidate = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(candidate, dict):
                    envelope = candidate
                    break
            if envelope is None:
                try:
                    candidate = json.loads(text)
                    envelope = candidate if isinstance(candidate, dict) else None
                except json.JSONDecodeError:
                    envelope = None
        if envelope is None:
            message = (err or out or f"exit code {code}").strip()
            kind, retryable = _classify(message)
            raise LLMError(kind, message[-300:], retryable=retryable)

        usage = envelope.get("usage") or {}
        response = LLMResponse(
            text="",
            model=self.model,
            input_tokens=usage.get("input_tokens") or 0,
            output_tokens=usage.get("output_tokens") or 0,
            cache_read_tokens=usage.get("cache_read_input_tokens") or 0,
            cache_write_tokens=usage.get("cache_creation_input_tokens") or 0,
            latency_ms=(time.monotonic() - t0) * 1000,
            stop_reason=envelope.get("subtype"),
            served_by="claude-code",
            cost_usd=0.0,  # covered by the subscription
        )
        if envelope.get("is_error") or code != 0:
            message = str(envelope.get("result") or err or envelope.get("subtype") or "error")
            kind, retryable = _classify(message)
            raise LLMError(kind, message[-300:], retryable=retryable, response=response)
        if self.session_mode == "per_agent":
            self._started.add(sid)
        structured = envelope.get("structured_output")
        if isinstance(structured, dict):
            response.text = json.dumps(structured)
        else:
            response.text = str(envelope.get("result") or "")
        if not response.text:
            raise LLMError("empty_response", str(envelope.get("subtype")), response=response)
        return response

    async def close(self) -> None:
        return None


async def cli_status() -> dict[str, Any]:
    """Whether the CLI is installed on the server, and its version (for the setup page)."""
    exe = find_cli()
    if not exe:
        return {"available": False, "version": None}
    try:
        proc = await asyncio.create_subprocess_exec(
            exe, "--version", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
        version = out.decode(errors="replace").strip().splitlines()[0] if out else None
    except (OSError, asyncio.TimeoutError, IndexError):
        version = None
    return {"available": True, "version": version}
