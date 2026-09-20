"""Argument parsing and dispatch."""
import argparse
import os
import sys

from .commands import (
    _pkg_version,
    cmd_doctor,
    cmd_dryrun,
    cmd_extras,
    cmd_share,
    cmd_status,
    cmd_widget,
)
from .config import load_config, resolve_config
from .job import run_job
from .llm import _GEMINI_MODEL
from .output import _purge_video
from .pdf import md_to_pdf
from .selftest import _self_test
from .tui import cmd_setup, tui


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "status":
        d = sys.argv[2] if len(sys.argv) > 2 and not sys.argv[2].startswith("-") else "."
        cmd_status(d, "--json" in sys.argv)
        return
    if len(sys.argv) > 1 and sys.argv[1] == "setup":
        cmd_setup("--advanced" in sys.argv)
        return
    if len(sys.argv) > 1 and sys.argv[1] == "doctor":
        px = None
        if "--proxy" in sys.argv:
            i = sys.argv.index("--proxy")
            px = sys.argv[i + 1] if i + 1 < len(sys.argv) else None
        cmd_doctor(px)
        return
    if len(sys.argv) > 1 and sys.argv[1] == "serve":
        from .web import cmd_serve
        cmd_serve(sys.argv[2:])
        return
    if len(sys.argv) > 1 and sys.argv[1] == "widget":
        cmd_widget()
        return
    if len(sys.argv) > 1 and sys.argv[1] == "share":
        cmd_share()
        return
    if len(sys.argv) > 1 and sys.argv[1] == "extras":
        cmd_extras()
        return
    if len(sys.argv) > 1 and sys.argv[1] == "pdf":
        if len(sys.argv) < 3:
            print("Usage: tube2note pdf <file.md> [...]")
            return
        for f in sys.argv[2:]:
            try:
                print("PDF: " + md_to_pdf(f), flush=True)
            except (OSError, SystemExit) as e:
                print(f"! {f}: {e}")
        return
    ap = argparse.ArgumentParser(prog="tube2note", description="YouTube -> single Markdown (NotebookLM feed)")
    ap.add_argument("urls", nargs="*", help="channel / playlist / video URLs")
    ap.add_argument("-o", "--out", default="tube2note.md")
    ap.add_argument("--lang", default=None, help="subtitle language priority, comma separated")
    ap.add_argument("--max", type=int, default=100, help="max number of videos")
    ap.add_argument("--sleep", type=float, default=2.0, help="pause between videos (s)")
    ap.add_argument("--chunk", type=int, default=None, help="long break every N videos")
    ap.add_argument("--chunk-cooldown", type=int, default=None, help="break between chunks (s)")
    ap.add_argument("--fetch-gap", type=int, default=None, help="max pause before subtitle fetch, seconds (default 10)")
    ap.add_argument("--workers", type=int, default=1, help="parallel fetch workers 1-4 (default 1, serial and safest)")
    ap.add_argument("--throttle-cooldown", type=int, default=1800, help="break after 5 throttles in a row (s)")
    ap.add_argument("-d", "--dir", default=None, help="output folder (created if missing)")
    ap.add_argument("--layout", default=None, help="output layout: single, videos or tree")
    ap.add_argument("--timestamps", action="store_true", default=None, help="keep [MM:SS] markers in transcripts")
    ap.add_argument("--clean", dest="clean", action="store_true", default=None, help="clean transcripts (default on)")
    ap.add_argument("--no-clean", dest="clean", action="store_false", help="keep raw transcripts")
    ap.add_argument("--since", default=None, help="only videos published on/after YYYY-MM-DD")
    ap.add_argument("--resume-last", action="store_true", help="re-run the last saved collection job")
    ap.add_argument("--redo", default=None, help="re-process video ID(s), comma separated (clears cache + old output)")
    ap.add_argument("--name-template", default=None, help='per-video path template, e.g. "{channel}/{title} [{id}]"')
    ap.add_argument("--profile", default=None, help="config profile name (or YT2MD_PROFILE)")
    ap.add_argument("--split-words", type=int, default=0, help="auto-split finished file into N-word parts (0=off)")
    ap.add_argument("--pdf", action="store_true", help="also write PDF next to the Markdown (needs fpdf2)")
    ap.add_argument("--transcribe", action="store_true", help="transcribe captionless videos via Gemini API (needs GEMINI_API_KEY)")
    ap.add_argument("--engine", default="api", help="transcribe engine: api or local (whisper.cpp extra)")
    ap.add_argument("--yes", action="store_true", help="auto-answer yes to extra download prompts")
    ap.add_argument("--summarize", action="store_true", help="add Gemini summary per video (needs GEMINI_API_KEY)")
    ap.add_argument("--translate", default=None, help="translate transcript to LANG via Gemini (needs GEMINI_API_KEY), e.g. tr")
    ap.add_argument("--gemini-model", default=None, help="Gemini model for transcribe/summarize (default: gemini-2.5-flash-lite)")
    ap.add_argument("--proxy", default=None, help="proxy URL for all requests (yt-dlp syntax, e.g. socks5://127.0.0.1:1080)")
    ap.add_argument("--cookies", default=None, help="Netscape cookies.txt file (helps logged-in/age-gated content)")
    ap.add_argument("--tui", action="store_true", help="interactive mode (short command)")
    ap.add_argument("--verbose", action="store_true", help="scrolling log lines instead of the live dashboard")
    ap.add_argument("--dry-run", action="store_true", help="list + estimate only, download nothing")
    ap.add_argument("--fresh", action="store_true", help="discard previous progress, start over")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--version", action="store_true", help="print version and exit")
    a = ap.parse_args()
    if a.self_test:
        _self_test()
        return
    if a.version:
        print(f"tube2note {_pkg_version()}")
        return
    if a.tui or (not a.urls and not a.redo and not a.resume_last):
        try:
            tui()
        except (KeyboardInterrupt, EOFError):
            print("\nExit.")
        return
    profile = a.profile or os.environ.get("YT2MD_PROFILE") or None
    cfg = resolve_config({"outdir": a.dir, "layout": a.layout, "lang": a.lang,
                          "chunk": a.chunk, "timestamps": a.timestamps,
                          "chunk_cooldown_min": (a.chunk_cooldown // 60
                                                 if a.chunk_cooldown is not None else None),
                          "template": a.name_template, "clean": a.clean}, profile)
    fetch_gap = a.fetch_gap if a.fetch_gap is not None else 10
    workers = min(4, max(1, a.workers or 1))
    if a.redo:
        _out = os.path.join(os.path.expanduser(cfg["outdir"]), a.out) if cfg["outdir"] != "." else a.out
        _root = os.path.dirname(os.path.abspath(_out))
        for _v in [x.strip() for x in a.redo.split(",") if x.strip()]:
            got = _purge_video(_out, _root, cfg["layout"], _v)
            print(f"redo {_v}: cleared {', '.join(got) or 'nothing found'}")
        a.urls = list(a.urls) + [f"https://www.youtube.com/watch?v={_v.strip()}"
                                 for _v in a.redo.split(",") if _v.strip()]
    if a.dry_run:
        cmd_dryrun(a.urls, a.max, cfg["lang"])
        return
    if a.resume_last:
        store = load_config()
        last = (store.get("last:" + profile) if profile else None) or store.get("last")
        if not last or not last.get("urls"):
            ap.error("no saved job: run once first (resume info is stored automatically)")
        run_job(last["urls"], last.get("out", "tube2note.md"), last.get("lang", cfg["lang"]),
                last.get("max_n", 100), last.get("sleep", 2.0), False, last.get("chunk", 50),
                last.get("chunk_cooldown", 600), a.throttle_cooldown,
                outdir=last.get("outdir", "."), ts=last.get("ts", False),
                split_words=last.get("split_words", 0), verbose=a.verbose,
                layout=last.get("layout", "single"), template=last.get("template", ""),
                pdf=a.pdf, proxy=last.get("proxy"), cookiefile=last.get("cookiefile"),
                since=last.get("since"), translate=last.get("translate"))
        return
    run_job(a.urls, a.out, cfg["lang"], a.max, a.sleep, a.fresh, cfg["chunk"],
            cfg["chunk_cooldown_min"] * 60, a.throttle_cooldown, outdir=cfg["outdir"],
            ts=cfg["timestamps"], split_words=a.split_words, verbose=a.verbose,
            layout=cfg["layout"], template=cfg["template"], pdf=a.pdf,
            proxy=a.proxy, cookiefile=a.cookies, since=a.since, profile=profile,
            fetch_gap=fetch_gap, workers=workers, clean=cfg["clean"],
            transcribe=a.transcribe, summarize=a.summarize,
            gemini_model=a.gemini_model or _GEMINI_MODEL, engine=a.engine,
            translate=a.translate, auto_yes=a.yes)
