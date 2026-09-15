#!/usr/bin/env python3
"""
Export a Scrim Claude Code session from its JSONL to MD and clean JSON.

Usage:
    python3 export_session.py [session_id]

If session_id is omitted, uses the most recently modified JSONL in
~/.claude/projects/-home-user-scrim-routine-anchor/

Output files are written to exports/ in the current working directory.
"""

import json
import os
import sys
import glob
from datetime import datetime, timezone


PROJECTS_DIR = os.path.expanduser(
    "~/.claude/projects/-home-user-scrim-routine-anchor"
)


def find_jsonl(session_id=None):
    if session_id:
        path = os.path.join(PROJECTS_DIR, f"{session_id}.jsonl")
        if not os.path.exists(path):
            raise FileNotFoundError(f"No JSONL found for session {session_id}")
        return path
    files = glob.glob(os.path.join(PROJECTS_DIR, "*.jsonl"))
    if not files:
        raise FileNotFoundError(f"No JSONL files found in {PROJECTS_DIR}")
    return max(files, key=os.path.getmtime)


def parse_conversation(jsonl_path):
    with open(jsonl_path) as f:
        lines = f.readlines()

    turns = []
    pending_assistant = {"texts": [], "tools": [], "thinking": []}

    def flush_assistant():
        if pending_assistant["texts"] or pending_assistant["tools"]:
            turns.append({
                "role": "assistant",
                "texts": pending_assistant["texts"][:],
                "tools": pending_assistant["tools"][:],
                "thinking": pending_assistant["thinking"][:],
            })
            pending_assistant["texts"].clear()
            pending_assistant["tools"].clear()
            pending_assistant["thinking"].clear()

    session_id = None
    timestamps = []

    for line in lines:
        obj = json.loads(line)
        t = obj.get("type", "")
        ts = obj.get("timestamp")
        if ts:
            timestamps.append(ts)

        if not session_id:
            session_id = obj.get("sessionId")

        if t == "user":
            msg = obj.get("message", {})
            if msg.get("role") == "user":
                flush_assistant()
                content = msg.get("content", "")
                if isinstance(content, str):
                    if content.strip():
                        turns.append({"role": "user", "text": content, "timestamp": ts})
                elif isinstance(content, list):
                    texts = [
                        item["text"] for item in content
                        if isinstance(item, dict) and item.get("type") == "text"
                    ]
                    if texts:
                        turns.append({
                            "role": "user",
                            "text": "\n".join(texts),
                            "timestamp": ts,
                        })

        elif t == "assistant":
            msg = obj.get("message", {})
            content = msg.get("content", [])
            if isinstance(content, list):
                for item in content:
                    if not isinstance(item, dict):
                        continue
                    kind = item.get("type")
                    if kind == "text":
                        pending_assistant["texts"].append(item["text"])
                        if not pending_assistant.get("timestamp"):
                            pending_assistant["timestamp"] = ts
                    elif kind == "tool_use":
                        pending_assistant["tools"].append({
                            "name": item.get("name", ""),
                            "input": item.get("input", {}),
                        })
                    elif kind == "thinking":
                        pending_assistant["thinking"].append(item.get("thinking", ""))

    flush_assistant()

    started_at = timestamps[0] if timestamps else None
    return session_id, started_at, turns


def to_md(session_id, started_at, turns, include_tools=True, include_thinking=False):
    lines = []
    lines.append(f"# Scrim Session Export\n")
    lines.append(f"**Session ID:** `{session_id}`  ")
    if started_at:
        lines.append(f"**Started:** {started_at}  ")
    lines.append(f"**Exported:** {datetime.now(timezone.utc).isoformat()}  ")
    lines.append(f"**Turns:** {len(turns)}\n")
    lines.append("---\n")

    for i, turn in enumerate(turns, 1):
        role = turn["role"]
        if role == "user":
            lines.append(f"## {i}. Vikki\n")
            lines.append(turn["text"])
            lines.append("\n")
        elif role == "assistant":
            lines.append(f"## {i}. Scrim\n")
            if include_thinking and turn.get("thinking"):
                lines.append("<details><summary>Thinking</summary>\n")
                for block in turn["thinking"]:
                    lines.append(block)
                    lines.append("\n")
                lines.append("</details>\n\n")
            for text in turn["texts"]:
                lines.append(text)
                lines.append("\n")
            if include_tools and turn.get("tools"):
                tool_names = [t["name"] for t in turn["tools"]]
                lines.append(
                    f"\n*[Tool calls: {', '.join(f'`{n}`' for n in tool_names)}]*\n"
                )
        lines.append("\n")

    return "\n".join(lines)


def to_clean_json(session_id, started_at, turns):
    return {
        "session_id": session_id,
        "started_at": started_at,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "turn_count": len(turns),
        "turns": [
            {
                "turn": i + 1,
                "role": t["role"],
                "text": "\n".join(t["texts"]) if t["role"] == "assistant" else t.get("text", ""),
                "tools": t.get("tools", []) if t["role"] == "assistant" else [],
                "timestamp": t.get("timestamp"),
            }
            for i, t in enumerate(turns)
        ],
    }


def main():
    session_id_arg = sys.argv[1] if len(sys.argv) > 1 else None
    jsonl_path = find_jsonl(session_id_arg)
    print(f"Reading: {jsonl_path}")

    session_id, started_at, turns = parse_conversation(jsonl_path)
    print(f"Session: {session_id}")
    print(f"Turns:   {len(turns)}")

    exports_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "exports")
    os.makedirs(exports_dir, exist_ok=True)

    # Date prefix from started_at or now
    if started_at:
        date_prefix = started_at[:10]
    else:
        date_prefix = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    short_id = session_id[:8] if session_id else "unknown"
    base = f"{date_prefix}_scrim-interactive_{short_id}"

    # Raw JSONL copy (local only, not committed to repo)
    jsonl_out = os.path.join(exports_dir, f"{base}.jsonl")
    with open(jsonl_path) as src, open(jsonl_out, "w") as dst:
        dst.write(src.read())
    print(f"JSONL:   {jsonl_out}  (local only)")

    # Clean JSON
    json_out = os.path.join(exports_dir, f"{base}.json")
    with open(json_out, "w") as f:
        json.dump(to_clean_json(session_id, started_at, turns), f, indent=2, ensure_ascii=False)
    print(f"JSON:    {json_out}")

    # Markdown
    md_out = os.path.join(exports_dir, f"{base}.md")
    with open(md_out, "w") as f:
        f.write(to_md(session_id, started_at, turns))
    print(f"MD:      {md_out}")


if __name__ == "__main__":
    main()
