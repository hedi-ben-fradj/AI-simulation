#!/usr/bin/env python3
"""Stand-in for the Claude Code CLI in tests (print mode with --output-format json).

FAKE_CLAUDE_LOG: file to append one JSON line per call (argv, stdin, selected env).
FAKE_CLAUDE_STATE: directory remembering created session IDs.
FAKE_CLAUDE_MODE: ok | not_logged_in | slow | text_only
"""
import json
import os
import sys
import time

args = sys.argv[1:]
if "--help" in args:
    print("Usage: claude [options]\n  -p, --print\n  --output-format <format>\n  --model <model>\n"
          "  --system-prompt <prompt>\n  --json-schema <schema>\n  --tools <tools...>\n  --strict-mcp-config\n"
          "  --effort <level>\n  --session-id <uuid>\n  -r, --resume [value]\n  --no-session-persistence")
    sys.exit(0)
if "--version" in args:
    print("9.9.9 (Claude Code)")
    sys.exit(0)

stdin = sys.stdin.read()
mode = os.environ.get("FAKE_CLAUDE_MODE", "ok")
log = os.environ.get("FAKE_CLAUDE_LOG")
if log:
    with open(log, "a") as fh:
        fh.write(json.dumps({"argv": args, "stdin": stdin, "cwd": os.getcwd(),
                             "has_api_key": "ANTHROPIC_API_KEY" in os.environ}) + "\n")


def value(flag):
    return args[args.index(flag) + 1] if flag in args else None


state = os.environ.get("FAKE_CLAUDE_STATE", "/tmp")
sid = value("--session-id") or value("--resume")
if sid:
    marker = os.path.join(state, sid)
    if "--session-id" in args and os.path.exists(marker):
        print(f"Error: Session ID {sid} is already in use.", file=sys.stderr)
        sys.exit(1)
    if "--resume" in args and not os.path.exists(marker):
        print(f"No conversation found with session ID: {sid}", file=sys.stderr)
        sys.exit(1)
    open(marker, "w").close()

if mode == "not_logged_in":
    print(json.dumps({"type": "result", "subtype": "success", "is_error": True,
                      "result": "Not logged in · Please run /login"}))
    sys.exit(1)
if mode == "slow":
    time.sleep(30)

decision = {"action": "rest", "target": None, "duration": 2, "quantity": None, "resource_offer": None,
            "resource_request": None, "message": None, "message_to": None,
            "visible_intention": "Resting a little.", "memory_candidates": [], "belief": None, "confidence": 0.6}
envelope = {"type": "result", "subtype": "success", "is_error": False, "session_id": sid or "x",
            "total_cost_usd": 0.01, "usage": {"input_tokens": 120, "output_tokens": 40,
                                              "cache_read_input_tokens": 900, "cache_creation_input_tokens": 0}}
if mode == "text_only":
    envelope["result"] = "Here is my decision:\n```json\n" + json.dumps(decision) + "\n```"
else:
    envelope["result"] = ""
    envelope["structured_output"] = decision
print(json.dumps(envelope))
