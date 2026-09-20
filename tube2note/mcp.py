"""Minimal MCP server over stdio (JSON-RPC 2.0): tools/list + tools/call.

Pair with any MCP client:
  {"mcpServers": {"tube2note": {"command": "tube2note", "args": ["mcp"]}}}
"""
import contextlib
import io
import json
import sys

from . import __version__

TOOLS = [
    {"name": "download",
     "description": "Download YouTube transcripts (channel/playlist/video URLs) into Markdown.",
     "inputSchema": {"type": "object",
                     "properties": {
                         "url": {"type": "string", "description": "YouTube URL (video, channel, playlist)"},
                         "out": {"type": "string", "description": "output markdown filename"},
                         "outdir": {"type": "string", "description": "output folder"},
                         "max": {"type": "integer", "description": "max videos"},
                         "lang": {"type": "string", "description": "subtitle languages, e.g. 'tr,en'"},
                         "layout": {"type": "string", "enum": ["single", "videos", "tree"]},
                         "summarize": {"type": "boolean", "description": "needs GEMINI_API_KEY"},
                         "translate": {"type": "string", "description": "target lang, needs GEMINI_API_KEY"},
                         "link_timestamps": {"type": "boolean", "description": "clickable timestamp links"},
                         "srt": {"type": "boolean", "description": "write .srt sidecar per video"}},
                     "required": ["url"]}},
    {"name": "status",
     "description": "Collection progress (done/skipped counts) for a folder.",
     "inputSchema": {"type": "object",
                     "properties": {"dir": {"type": "string", "description": "folder with collections"}},
                     "required": []}},
    {"name": "dry_run",
     "description": "List videos + estimate without downloading.",
     "inputSchema": {"type": "object",
                     "properties": {"url": {"type": "string", "description": "YouTube URL"},
                                    "max": {"type": "integer"},
                                    "lang": {"type": "string"}},
                     "required": ["url"]}},
]


def _text(s):
    return {"content": [{"type": "text", "text": s}]}


def _call(name, args):
    args = args or {}
    if name == "download":
        from .config import resolve_config
        from .job import _exit_code, run_job
        cfg = resolve_config({"outdir": args.get("outdir"), "layout": args.get("layout"),
                              "lang": args.get("lang")}, None)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):  # progress bars must not corrupt the RPC stream
            res = run_job([args["url"]], args.get("out", "tube2note.md"), cfg["lang"],
                          int(args.get("max", 100)), 2.0, videos=None,
                          outdir=cfg["outdir"], layout=cfg["layout"],
                          summarize=bool(args.get("summarize")),
                          translate=args.get("translate"),
                          link_timestamps=bool(args.get("link_timestamps")),
                          srt=bool(args.get("srt")))
        tail = "\n".join(buf.getvalue().splitlines()[-5:])
        return _text(f"exit={_exit_code(res)}\n{tail}")
    if name == "status":
        from .commands import cmd_status
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            cmd_status(args.get("dir", "."), True)
        return _text(buf.getvalue() or "No collections.")
    if name == "dry_run":
        from .source import detect_langs, expand
        videos, hint = expand([args["url"]], int(args.get("max", 100)))
        sug, found = detect_langs(videos)
        return _text(json.dumps({"source": hint, "videos": len(videos),
                                 "languages": sug, "found": found[:8]}, indent=2))
    raise ValueError(f"unknown tool: {name}")


def _handle(req):
    """Pure dispatch (unit-testable): (response_dict_or_None, shutdown_bool)."""
    rid, method, params = req.get("id"), req.get("method"), req.get("params") or {}
    if method in ("notifications/initialized", "notifications/cancelled"):
        return None, False
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": rid,
                "result": {"protocolVersion": "2024-11-05",
                           "capabilities": {"tools": {}},
                           "serverInfo": {"name": "tube2note", "version": __version__}}}, False
    if method == "ping":
        return {"jsonrpc": "2.0", "id": rid, "result": {}}, False
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": rid, "result": {"tools": TOOLS}}, False
    if method == "tools/call":
        try:
            return {"jsonrpc": "2.0", "id": rid,
                    "result": _call(params.get("name"), params.get("arguments"))}, False
        except Exception as e:
            return {"jsonrpc": "2.0", "id": rid,
                    "result": {"content": [{"type": "text", "text": f"error: {e}"}],
                               "isError": True}}, False
    return {"jsonrpc": "2.0", "id": rid,
            "error": {"code": -32601, "message": f"unknown method: {method}"}}, False


def cmd_mcp():
    """Serve MCP on stdio until EOF."""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except ValueError:
            continue
        resp, _ = _handle(req)
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()
