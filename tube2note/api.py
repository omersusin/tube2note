"""Stable SDK layer for future desktop/mobile apps. CLI/TUI/web/MCP call this, never job internals."""
from .config import resolve_config
from .job import _exit_code, run_job
from .llm import _GEMINI_MODEL
from .source import detect_langs, expand


def collect(urls, out="tube2note.md", profile=None, overrides=None, **kw):
    """One-call collection. Returns (exit_code, result_dict). All kwargs optional."""
    cfg = resolve_config(overrides or {}, profile)
    res = run_job(list(urls), out,
        kw.get("lang", cfg["lang"]), kw.get("max_n", kw.get("max", 100)),
        kw.get("sleep", 2.0), kw.get("fresh", False),
        kw.get("chunk", cfg["chunk"]), kw.get("chunk_cooldown", cfg["chunk_cooldown_min"] * 60),
        kw.get("throttle_cooldown", 1800),
        outdir=kw.get("outdir", cfg["outdir"]), ts=kw.get("ts", cfg["timestamps"]),
        split_words=kw.get("split_words", 0), verbose=kw.get("verbose", False),
        layout=kw.get("layout", cfg["layout"]), template=kw.get("template", cfg["template"]),
        pdf=kw.get("pdf", False), proxy=kw.get("proxy"),
        cookiefile=kw.get("cookiefile", kw.get("cookies")),
        since=kw.get("since"), profile=profile,
        fetch_gap=kw.get("fetch_gap", 10), workers=kw.get("workers", 1),
        clean=kw.get("clean", cfg["clean"]), clean_level=kw.get("clean_level", cfg["clean_level"]),
        transcribe=kw.get("transcribe", False), summarize=kw.get("summarize", False),
        gemini_model=kw.get("gemini_model") or _GEMINI_MODEL, engine=kw.get("engine", "api"),
        translate=kw.get("translate"), bilingual=kw.get("bilingual"), auto_yes=kw.get("auto_yes", False),
        link_timestamps=kw.get("link_timestamps", False), srt=kw.get("srt", False),
        epub=kw.get("epub", False), dedupe=kw.get("dedupe", True),
        obsidian=kw.get("obsidian", False), jsonl=kw.get("jsonl", False),
        ts_every=kw.get("ts_every", 0), single_line=kw.get("single_line", False),
        txt=kw.get("txt", False), videos=kw.get("videos"),
        cookies_from_browser=kw.get("cookies_from_browser"),
        vtt=kw.get("vtt", False), anki=kw.get("anki", False),
        chapters=kw.get("chapters", False), sponsorblock=kw.get("sponsorblock", False),
        cite=kw.get("cite", False), whisper_model=kw.get("whisper_model", "tiny"),
        diarize=kw.get("diarize", False), fast_subs=kw.get("fast_subs", False))
    return _exit_code(res), (res or {})

def list_videos(urls, max_n=100, since=None):
    return expand(urls, max_n, since)

def language_hint(videos):
    return detect_langs(videos)
