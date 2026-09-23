"""Argument parsing and dispatch."""
import argparse
import os
import sys

from . import job as _jobmod
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
from .job import _exit_code
from .llm import _GEMINI_MODEL


def run_job(*a, **k):
    # ponytail: drop unknown kwargs for old job.py; remove when job.py accepts new flags
    import inspect as _inspect
    _fn = _jobmod.run_job
    try:
        _params = _inspect.signature(_fn).parameters
        if not any(p.kind == _inspect.Parameter.VAR_KEYWORD for p in _params.values()):
            k = {kk: vv for kk, vv in k.items() if kk in _params}
    except (ValueError, TypeError):
        pass
    return _fn(*a, **k)
from .output import _purge_video
from .pdf import md_to_pdf
from .selftest import _self_test
from .tui import cmd_setup, tui


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "status":
        _sargs = sys.argv[2:]
        _sdirs = [x for x in _sargs if not x.startswith("-")]
        cmd_status(_sdirs[0] if _sdirs else ".", "--json" in _sargs)
        return
    if len(sys.argv) > 1 and sys.argv[1] == "setup":
        cmd_setup("--advanced" in sys.argv)
        return
    if len(sys.argv) > 1 and sys.argv[1] == "doctor":
        px = None
        if "--proxy" in sys.argv:
            i = sys.argv.index("--proxy")
            px = sys.argv[i + 1] if i + 1 < len(sys.argv) else None
            if not px or px.startswith("-"):
                print("doctor: --proxy needs a URL (e.g. socks5://127.0.0.1:1080)")
                return
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
        cmd_extras(sys.argv[2:])
        return
    if len(sys.argv) > 1 and sys.argv[1] == "watch":
        from .watch import cmd_watch
        raise SystemExit(cmd_watch(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "search":
        from .search import search_collections
        _q, _d, _j = "", ".", "--json" in sys.argv[2:]
        _rest = sys.argv[2:]
        _k = 0
        while _k < len(_rest):
            if _rest[_k] == "-d":
                if _k + 1 >= len(_rest) or _rest[_k + 1].startswith("-"):
                    print("search: -d needs a directory")
                    raise SystemExit(2)
                _d = _rest[_k + 1]
                _k += 2
            elif _rest[_k] == "--json":
                _k += 1
            elif not _rest[_k].startswith("-") and not _q:
                _q = _rest[_k]
                _k += 1
            else:
                _k += 1
        raise SystemExit(search_collections(_q, _d, _j))
    if len(sys.argv) > 1 and sys.argv[1] == "serve-api":
        from .server_api import main as _api_main
        raise SystemExit(_api_main())
    if len(sys.argv) > 1 and sys.argv[1] == "mcp":
        from .mcp import cmd_mcp
        cmd_mcp()
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
    if len(sys.argv) > 1 and sys.argv[1] == "epub":
        from .epub import md_to_epub
        if len(sys.argv) < 3:
            print("Usage: tube2note epub <file.md> [...]")
            return
        for f in sys.argv[2:]:
            try:
                print("EPUB: " + md_to_epub(f), flush=True)
            except OSError as e:
                print(f"! {f}: {e}")
        return
    ap = argparse.ArgumentParser(prog="tube2note", description="YouTube -> single Markdown (NotebookLM feed)",
        epilog="Subcommands: status, setup, doctor, serve, widget, share, extras, watch, search, serve-api, mcp, pdf, epub\n"
               "examples:\n"
               "  tube2note 'https://www.youtube.com/playlist?list=PL...' -o out.md\n"
               "  tube2note --resume-last\n"
               "  tube2note status ./out --json\n"
               "  tube2note --vtt --anki --chapters --sponsorblock --cite URL\n"
               "  tube2note --engine local --whisper-model base URL")
    ap.add_argument("urls", nargs="*", help="channel / playlist / video URLs")
    g_src = ap.add_argument_group("Sources", "what to collect")
    g_src.add_argument("--max", type=int, default=None, help="max number of videos")
    g_src.add_argument("--since", default=None, help="only videos published on/after YYYY-MM-DD")
    g_src.add_argument("--redo", default=None, help="re-process video ID(s), comma separated (clears cache + old output)")
    g_src.add_argument("--resume-last", action="store_true", help="re-run the last saved collection job")
    g_src.add_argument("--fresh", action="store_true", help="discard previous progress, start over")
    g_out = ap.add_argument_group("Output", "where the notes go")
    g_out.add_argument("-o", "--out", default="tube2note.md")
    g_out.add_argument("-d", "--dir", default=None, help="output folder (created if missing)")
    g_out.add_argument("--layout", default=None, help="output layout: single, videos or tree")
    g_out.add_argument("--name-template", default=None, help='per-video path template, e.g. "{channel}/{title} [{id}]"')
    g_out.add_argument("--split-words", type=int, default=None, help="auto-split finished file into N-word parts (0=off)")
    g_out.add_argument("--jsonl", action="store_true", help="also append one JSON line per video to <out>.jsonl")
    g_out.add_argument("--pdf", action="store_true", help="also write PDF next to the Markdown (needs fpdf2)")
    g_out.add_argument("--epub", action="store_true", help="also write EPUB next to the Markdown (stdlib, for e-readers)")
    g_out.add_argument("--obsidian", action="store_true",
                    help="Obsidian-friendly notes: tags+aliases in frontmatter (pairs with --layout videos)")
    g_out.add_argument("--no-dedupe", dest="no_dedupe", action="store_true",
                    help="keep duplicate transcripts (default: skip same-text re-uploads)")
    g_fmt = ap.add_argument_group("Formats", "transcript extras and sidecars")
    g_fmt.add_argument("--timestamps", action="store_true", default=None, help="keep [MM:SS] markers in transcripts")
    g_fmt.add_argument("--link-timestamps", dest="link_timestamps", action="store_true", default=None,
                    help="clickable [MM:SS](youtu.be?t=Ns) links (implies timestamps)")
    g_fmt.add_argument("--no-link-timestamps", dest="link_timestamps", action="store_false",
                    help="turn off clickable links (e.g. on --resume-last)")
    g_fmt.add_argument("--srt", dest="srt", action="store_true", default=None,
                    help="write a .srt sidecar per video")
    g_fmt.add_argument("--no-srt", dest="srt", action="store_false",
                    help="turn off .srt (e.g. on --resume-last)")
    g_fmt.add_argument("--vtt", dest="vtt", action="store_true", default=None,
                    help="write a .vtt sidecar per video")
    g_fmt.add_argument("--no-vtt", dest="vtt", action="store_false",
                    help="turn off .vtt (e.g. on --resume-last)")
    g_fmt.add_argument("--txt", dest="txt", action="store_true", default=None,
                    help="write a .txt sidecar per video (clean text for RAG/Anki)")
    g_fmt.add_argument("--no-txt", dest="txt", action="store_false",
                    help="turn off .txt (e.g. on --resume-last)")
    g_fmt.add_argument("--anki", dest="anki", action="store_true", default=None,
                    help="write Anki flashcards (.csv + .md) from summaries")
    g_fmt.add_argument("--no-anki", dest="anki", action="store_false",
                    help="turn off Anki (e.g. on --resume-last)")
    g_fmt.add_argument("--chapters", dest="chapters", action="store_true", default=None,
                    help="group transcript by video chapters")
    g_fmt.add_argument("--no-chapters", dest="chapters", action="store_false",
                    help="turn off chapters (e.g. on --resume-last)")
    g_fmt.add_argument("--sponsorblock", dest="sponsorblock", action="store_true", default=None,
                    help="skip sponsor segments via SponsorBlock")
    g_fmt.add_argument("--no-sponsorblock", dest="sponsorblock", action="store_false",
                    help="turn off SponsorBlock (e.g. on --resume-last)")
    g_fmt.add_argument("--cite", dest="cite", action="store_true", default=None,
                    help="append APA/MLA/Chicago/BibTeX/RIS citations")
    g_fmt.add_argument("--no-cite", dest="cite", action="store_false",
                    help="turn off citations (e.g. on --resume-last)")
    g_fmt.add_argument("--ts-every", type=int, default=None,
                    help="keep 1 timestamp per N seconds (0=all, e.g. --ts-every 30)")
    g_fmt.add_argument("--single-line", dest="single_line", action="store_true", default=None,
                    help="single-line transcript, markers inline (Obsidian compact mode)")
    g_fmt.add_argument("--clean", dest="clean", action="store_true", default=None, help="clean transcripts (default on)")
    g_fmt.add_argument("--no-clean", dest="clean", action="store_false", help="keep raw transcripts")
    g_fmt.add_argument("--clean-level", default=None, help="cleaning strength: light or full (default full)")
    g_ai = ap.add_argument_group("AI", "transcription, summary, translation (needs GEMINI_API_KEY unless --engine local)")
    g_ai.add_argument("--transcribe", action="store_true", help="transcribe captionless videos via Gemini API (needs GEMINI_API_KEY)")
    g_ai.add_argument("--engine", default=None, help="transcribe engine: api or local (whisper.cpp extra)")
    g_ai.add_argument("--whisper-model", dest="whisper_model", default=None, choices=["tiny", "base"],
                    help="whisper.cpp model for --engine local (default tiny)")
    g_ai.add_argument("--summarize", action="store_true", help="add Gemini summary per video (needs GEMINI_API_KEY)")
    g_ai.add_argument("--translate", default=None, help="translate transcript to LANG via Gemini (needs GEMINI_API_KEY), e.g. tr")
    g_ai.add_argument("--bilingual", default=None, help="source + translation interleaved per paragraph via Gemini (needs GEMINI_API_KEY), e.g. tr")
    g_ai.add_argument("--gemini-model", default=None, help="Gemini model for transcribe/summarize (default: gemini-2.5-flash-lite)")
    g_adv = ap.add_argument_group("Advanced", "fetching, auth, misc")
    g_adv.add_argument("--lang", default=None, help="subtitle language priority, comma separated")
    g_adv.add_argument("--sleep", type=float, default=None, help="pause between videos (s)")
    g_adv.add_argument("--chunk", type=int, default=None, help="long break every N videos")
    g_adv.add_argument("--chunk-cooldown", type=int, default=None, help="break between chunks (s)")
    g_adv.add_argument("--fetch-gap", type=int, default=None, help="max pause before subtitle fetch, seconds (default 10)")
    g_adv.add_argument("--workers", type=int, default=None, help="parallel fetch workers 1-4 (default 1, serial and safest)")
    g_adv.add_argument("--throttle-cooldown", type=int, default=1800, help="break after 5 throttles in a row (s)")
    g_adv.add_argument("--proxy", default=None, help="proxy URL for all requests (yt-dlp syntax, e.g. socks5://127.0.0.1:1080)")
    g_adv.add_argument("--cookies", default=None, help="Netscape cookies.txt file (helps logged-in/age-gated content)")
    g_adv.add_argument("--cookies-from-browser", default=None,
                    help="read cookies from a browser, e.g. chrome, firefox, 'chrome:Profile 1'")
    g_adv.add_argument("--yes", action="store_true", help="auto-answer yes to extra download prompts")
    g_adv.add_argument("--profile", default=None, help="config profile name (or YT2MD_PROFILE)")
    g_adv.add_argument("--tui", action="store_true", help="interactive mode (short command)")
    g_adv.add_argument("--verbose", action="store_true", help="scrolling log lines instead of the live dashboard")
    g_adv.add_argument("--dry-run", action="store_true", help="list + estimate only, download nothing")
    g_adv.add_argument("--self-test", action="store_true")
    g_adv.add_argument("--version", action="store_true", help="print version and exit")
    a = ap.parse_args()
    if a.self_test:
        _self_test()
        return
    if a.version:
        print(f"tube2note {_pkg_version()}")
        return
    if a.bilingual and a.translate:
        ap.error("--bilingual and --translate are mutually exclusive")
    if a.resume_last:
        if a.urls:
            ap.error("--resume-last takes no URLs (it re-runs the saved job)")
        if a.redo:
            ap.error("--resume-last cannot be combined with --redo")
        if a.fresh:
            ap.error("--resume-last cannot be combined with --fresh (it resumes progress)")
        if any(s == "-o" or s == "--out" or s.startswith("--out=") for s in sys.argv[2:]):
            ap.error("--resume-last cannot be combined with -o/--out (it resumes the saved file)")
        if any(s == "-d" or s == "--dir" or s.startswith("--dir=") for s in sys.argv[2:]):
            ap.error("--resume-last cannot be combined with -d/--dir (it resumes the saved folder)")
    if a.tui and (a.urls or a.redo or a.resume_last or a.dry_run or a.fresh):
        ap.error("--tui takes no URLs or job flags (it asks interactively)")
    if a.dry_run and a.redo:
        ap.error("--dry-run cannot be combined with --redo (--redo clears cache + output)")
    if a.out == "-":
        bad = []
        if a.pdf:
            bad.append("--pdf")
        if a.epub:
            bad.append("--epub")
        if a.srt:
            bad.append("--srt")
        if a.txt:
            bad.append("--txt")
        if a.vtt:
            bad.append("--vtt")
        if a.anki:
            bad.append("--anki")
        if a.chapters:
            bad.append("--chapters")
        if a.sponsorblock:
            bad.append("--sponsorblock")
        if a.cite:
            bad.append("--cite")
        if a.whisper_model:
            bad.append("--whisper-model")
        if (a.split_words or 0) > 0:
            bad.append("--split-words")
        if (a.layout or "single") != "single":
            bad.append("--layout")
        if getattr(a, "jsonl", False):
            bad.append("--jsonl")
        if bad:
            ap.error("incompatible with -o - (stdout): " + ", ".join(bad))
        if not a.urls and not a.redo and not a.resume_last:
            ap.error("no URLs for stdout mode")
    if len(a.urls) == 1:
        _u = a.urls[0]
        if "youtube.com" not in _u and "youtu.be" not in _u:
            import difflib as _difflib
            _subs = ["status", "setup", "doctor", "serve", "widget", "share", "extras",
                     "watch", "search", "serve-api", "mcp", "pdf", "epub"]
            _guess = _difflib.get_close_matches(_u, _subs, n=1, cutoff=0.7)
            _hint = f" (did you mean '{_guess[0]}'?)" if _guess else ""
            print(f"Hint: '{_u[:60]}' doesn't look like a YouTube URL (typo?){_hint}"
                  " e.g. tube2note 'https://www.youtube.com/watch?v=...'", file=sys.stderr)
    if a.tui:
        try:
            tui()
        except (KeyboardInterrupt, EOFError):
            print("\nExit.")
        return
    if not a.urls and not a.redo and not a.resume_last:
        try:
            _tty = sys.stdin.isatty()
        except (ValueError, AttributeError):
            _tty = False
        if _tty:
            try:
                tui()
            except (KeyboardInterrupt, EOFError):
                print("\nExit.")
            return
        ap.error("no URLs (e.g. tube2note 'https://www.youtube.com/playlist?list=...')")
    profile = a.profile or os.environ.get("YT2MD_PROFILE") or None
    if a.layout is not None and a.layout not in ("single", "videos", "tree"):
        print(f"Warning: unknown --layout '{a.layout}', using single.")
    cfg = resolve_config({"outdir": a.dir, "layout": a.layout, "lang": a.lang,
                          "chunk": a.chunk, "timestamps": a.timestamps,
                          "chunk_cooldown_min": None,
                          "template": a.name_template, "clean": a.clean,
                          "clean_level": a.clean_level, "vtt": a.vtt,
                          "anki": a.anki, "chapters": a.chapters,
                          "sponsorblock": a.sponsorblock, "cite": a.cite,
                          "whisper_model": a.whisper_model}, profile)
    max_n = max(1, a.max if a.max is not None else 100)
    sleep = max(0.0, a.sleep if a.sleep is not None else 2.0)
    chunk_cooldown = max(0, (a.chunk_cooldown if a.chunk_cooldown is not None
                             else cfg["chunk_cooldown_min"] * 60))
    if a.engine is not None and a.engine not in ("api", "local"):
        print(f"Warning: unknown --engine '{a.engine}', using api.")
    engine = a.engine if a.engine in ("api", "local") else "api"
    if a.clean_level is not None and a.clean_level not in ("light", "full"):
        print(f"Warning: unknown --clean-level '{a.clean_level}', using {cfg['clean_level']}.")
    clean_level = a.clean_level if a.clean_level in ("light", "full") else cfg["clean_level"]
    split_words = max(0, a.split_words if a.split_words is not None else 0)
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
        if a.resume_last:
            _store = load_config()
            _last = (_store.get("last:" + profile) if profile else None) or _store.get("last")
            if not _last or not _last.get("urls"):
                ap.error("no saved job: run once first (resume info is stored automatically)")
            cmd_dryrun(_last["urls"], max_n,
                       a.lang if a.lang is not None else _last.get("lang", cfg["lang"]))
        else:
            cmd_dryrun(a.urls, max_n, cfg["lang"])
        return
    if a.resume_last:
        store = load_config()
        last = (store.get("last:" + profile) if profile else None) or store.get("last")
        if not last or not last.get("urls"):
            ap.error("no saved job: run once first (resume info is stored automatically)")
        if (a.bilingual or last.get("bilingual")) and (a.translate or last.get("translate")):
            ap.error("--bilingual and --translate are mutually exclusive")
        r_layout = a.layout if a.layout is not None else last.get("layout", "single")
        if r_layout not in ("single", "videos", "tree"):
            print(f"Warning: unknown --layout '{a.layout}', using single.")
            r_layout = "single"
        return _exit_code(run_job(last["urls"], last.get("out", "tube2note.md"),
                a.lang if a.lang is not None else last.get("lang", cfg["lang"]),
                max(1, a.max if a.max is not None else last.get("max_n", 100)),
                max(0.0, a.sleep if a.sleep is not None else last.get("sleep", 2.0)),
                False, max(0, a.chunk if a.chunk is not None else last.get("chunk", 50)),
                max(0, (a.chunk_cooldown if a.chunk_cooldown is not None
                        else last.get("chunk_cooldown", 600))), a.throttle_cooldown,
                outdir=last.get("outdir", "."),
                ts=(a.timestamps if a.timestamps is not None else last.get("ts", False)),
                split_words=(max(0, a.split_words) if a.split_words is not None
                             else last.get("split_words", 0)), verbose=a.verbose,
                layout=r_layout,
                template=(a.name_template if a.name_template is not None
                          else last.get("template", "")),
                pdf=(a.pdf or last.get("pdf", False)),
                epub=(a.epub or last.get("epub", False)),
                obsidian=(a.obsidian or last.get("obsidian", False)),
                dedupe=(False if a.no_dedupe else last.get("dedupe", True)),
                proxy=(a.proxy or last.get("proxy")), cookiefile=(a.cookies or last.get("cookiefile")),
                cookies_from_browser=(a.cookies_from_browser or last.get("cookies_from_browser")),
                since=(a.since or last.get("since")),
                translate=(a.translate or last.get("translate")),
                bilingual=(a.bilingual or last.get("bilingual")),
                clean=(a.clean if a.clean is not None else last.get("clean", True)),
                clean_level=(a.clean_level if a.clean_level in ("light", "full")
                             else last.get("clean_level", "full")),
                link_timestamps=(a.link_timestamps if a.link_timestamps is not None
                                 else last.get("link_timestamps", False)),
                srt=(a.srt if a.srt is not None else last.get("srt", False)),
                ts_every=(a.ts_every if a.ts_every is not None else last.get("ts_every", 0)),
                single_line=(a.single_line if a.single_line is not None else last.get("single_line", False)),
                txt=(a.txt if a.txt is not None else last.get("txt", False)),
                jsonl=(a.jsonl or last.get("jsonl", False)),
                transcribe=(a.transcribe or last.get("transcribe", False)),
                summarize=(a.summarize or last.get("summarize", False)),
                gemini_model=(a.gemini_model or last.get("gemini_model")),
                engine=(a.engine if a.engine in ("api", "local")
                        else last.get("engine", "api")),
                fetch_gap=(a.fetch_gap if a.fetch_gap is not None else last.get("fetch_gap", 10)),
                workers=min(4, max(1, (a.workers if a.workers is not None
                                       else last.get("workers", 1)) or 1)),
                vtt=(a.vtt if a.vtt is not None else last.get("vtt", False)),
                anki=(a.anki if a.anki is not None else last.get("anki", False)),
                chapters=(a.chapters if a.chapters is not None else last.get("chapters", False)),
                sponsorblock=(a.sponsorblock if a.sponsorblock is not None
                              else last.get("sponsorblock", False)),
                cite=(a.cite if a.cite is not None else last.get("cite", False)),
                whisper_model=(a.whisper_model or last.get("whisper_model") or cfg["whisper_model"]),
                profile=profile, auto_yes=a.yes))
    _res = run_job(a.urls, a.out, cfg["lang"], max_n, sleep, a.fresh, cfg["chunk"],
            chunk_cooldown, a.throttle_cooldown, outdir=cfg["outdir"],
            ts=cfg["timestamps"], split_words=split_words, verbose=a.verbose,
            layout=cfg["layout"], template=cfg["template"], pdf=a.pdf,
            proxy=a.proxy, cookiefile=a.cookies, since=a.since, profile=profile,
            fetch_gap=fetch_gap, workers=workers, clean=cfg["clean"],
            clean_level=clean_level,
            transcribe=a.transcribe, summarize=a.summarize,
            gemini_model=a.gemini_model or _GEMINI_MODEL, engine=engine,
            translate=a.translate, bilingual=a.bilingual, auto_yes=a.yes,
            link_timestamps=bool(a.link_timestamps), srt=bool(a.srt), epub=a.epub,
            ts_every=(a.ts_every or 0), single_line=bool(a.single_line), txt=bool(a.txt),
            dedupe=not a.no_dedupe, obsidian=a.obsidian, jsonl=a.jsonl,
            cookies_from_browser=a.cookies_from_browser,
            vtt=cfg["vtt"], anki=cfg["anki"], chapters=cfg["chapters"],
            sponsorblock=cfg["sponsorblock"], cite=cfg["cite"],
            whisper_model=cfg["whisper_model"])
    return _exit_code(_res)
