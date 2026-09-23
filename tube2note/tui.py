"""Guided interactive mode."""
import os
import re

from .config import (
    CONFIG_PATH,
    DEFAULTS,
    _merge,
    is_first_run,
    load_config,
    resolve_config,
    save_config,
)
from .job import run_job
from .naming import slug
from .source import detect_langs, expand
from .ui import dim, green, panel, red, table

YT_RE = re.compile(r"(youtube\.com/(watch|shorts|playlist|@|channel/|c/|user/|live|embed)|youtu\.be/|[?&](list|v)=)")


def show_intro():
    print(panel("tube2note — YouTube to NotebookLM", [
        "Turn a channel, playlist or videos into Markdown + PDF.",
        "",
        "  HOW TO USE:",
        "  1. Paste link(s) and press Enter",
        "  2. Check the auto-detected summary table",
        "  3. Answer 2-3 questions (all have defaults)",
        "  4. Wait — the dashboard shows everything",
        "  5. Upload the .md (or _part files) to NotebookLM",
        "",
        "  TIPS: Ctrl+C stops safely, resume anytime.",
        "  Big file? Type 400000 at the split prompt.",
        "  More: 'yt setup' (defaults), 'yt status' (progress).",
        "",
        dim("NotebookLM cap: 500,000 words per source file."),
    ]))


def show_guide():
    print(panel("Quick guide", [
        "Paste any YouTube link: channel, playlist or video.",
        "The tool lists videos, guesses the file name + languages.",
        "Big jobs run in chunks with breaks (anti-429 protection).",
        "Progress is saved: Ctrl+C anytime, resume later.",
        "When done, upload the .md (or _part files) to NotebookLM.",
    ]))


def cmd_setup(advanced=False):
    """Personalize: 3 sticky defaults (folder, layout, language); pacing under --advanced."""
    store = load_config()
    cfg = _merge(dict(DEFAULTS), store, None, {}, {})
    print(panel("Personalize tube2note", ["CLI flags and YT2MD_* env vars always win over these."]))
    cfg["outdir"] = input(f"Default folder [{cfg['outdir']}] > ").strip() or cfg["outdir"]
    lay = input(f"Output layout (single/videos/tree) [{cfg['layout']}] > ").strip().lower() or cfg["layout"]
    cfg["layout"] = lay if lay in ("single", "videos", "tree") else "single"
    cfg["lang"] = input(f"Default languages [{cfg['lang']}] > ").strip() or cfg["lang"]
    if advanced:
        ts = input(f"Timestamps? (y/n) [{'y' if cfg['timestamps'] else 'n'}] > ").strip().lower()
        if ts in ("y", "yes", "n", "no"):
            cfg["timestamps"] = ts in ("y", "yes")
        try:
            cfg["chunk"] = max(0, int(input(f"Chunk size [{cfg['chunk']}] > ").strip() or cfg["chunk"]))
        except ValueError:
            pass
        try:
            cfg["chunk_cooldown_min"] = max(0, int(input(f"Chunk break minutes [{cfg['chunk_cooldown_min']}] > ").strip()
                                                    or cfg["chunk_cooldown_min"]))
        except ValueError:
            pass
        cfg["template"] = input(f"Name template [{cfg['template'] or 'layout default'}] > ").strip() \
            or cfg["template"]
    store["defaults"] = {k: cfg[k] for k in DEFAULTS if k in cfg}
    name = input("Save as profile name [skip] > ").strip()
    if name:
        store.setdefault("profiles", {})[name] = dict(store["defaults"])
        print(f"Profile '{name}': use with --profile {name} or YT2MD_PROFILE={name}")
    save_config(store)
    print(green("Saved to ") + CONFIG_PATH)
    return cfg


def tui():
    prof = os.environ.get("YT2MD_PROFILE") or None
    cfg = resolve_config(profile=prof)
    show_intro()
    if is_first_run():
        show_guide()
        if input("Personalize defaults now? (folder, layout...) [Y/n] > ").strip().lower() not in ("n", "no"):
            cmd_setup()
            cfg = resolve_config(profile=prof)
    while True:
        raw = input("\nURLs (space/comma separated, several allowed) > ").strip()
        if raw.lower() in ("q", "quit", "exit"):
            return
        urls = [u.strip(" ,") for u in re.split(r"[,\s]+", raw) if u.strip(" ,")]
        if not urls:
            print("No URLs, try again.")
            continue
        bad = [u for u in urls if not YT_RE.search(u)]
        if bad:
            print(red("Not a YouTube link: ") + ", ".join(bad))
            continue
        multi = len(urls) > 1 or any(x in u for u in urls
                                     for x in ("/playlist", "/@", "/channel", "/c/"))
        since = (input("Only videos since YYYY-MM-DD [any] > ").strip() or None) if multi else None
        print("Listing videos, wait...")
        videos, hint = expand(urls, 5000, since)
        if not videos:
            print("No videos found.")
            continue
        guess = slug(hint)
        print("Sampling subtitle languages...")
        sug, found = detect_langs(videos)
        est = len(videos) * 12 / 60
        print(table(["Setting", "Value"], [
            ["Source", (hint or urls[0])[:60]],
            ["Videos", str(len(videos))],
            ["File", guess],
            ["Languages", sug + (f"  (found: {', '.join(found[:8])})" if found else "")],
            ["Est. time", f"~{est:.0f} min paced" if est >= 1 else "<1 min"],
        ]))
        out = input(f"Output file [{guess}] > ").strip() or guess
        lastdir = load_config().get("lastdir") or cfg["outdir"]
        outdir = input(f"Folder [{lastdir}] > ").strip() or lastdir
        try:
            _st = load_config()
            _st["lastdir"] = outdir
            save_config(_st)
        except OSError:
            pass
        lay = input(f"Layout (single/videos/tree) [{cfg['layout']}] > ").strip().lower() or cfg["layout"]
        if lay not in ("single", "videos", "tree"):
            print(f"Unknown layout '{lay}', using single.")
            lay = "single"
        lang = input(f"Languages [{sug}] > ").strip() or sug
        mx = input(f"Max videos [{len(videos)}] > ").strip() or str(len(videos))
        try:
            max_n = max(1, int(mx))
        except ValueError:
            max_n = len(videos)
        videos = videos[:max_n]
        ch = input(f"Chunk size [{cfg['chunk']}] > ").strip() or str(cfg["chunk"])
        try:
            ch = max(0, int(ch))
        except ValueError:
            ch = cfg["chunk"]
        cd = input(f"Chunk break minutes [{cfg['chunk_cooldown_min']}] > ").strip() or str(cfg["chunk_cooldown_min"])
        try:
            chc = max(0, int(cd)) * 60
        except ValueError:
            chc = cfg["chunk_cooldown_min"] * 60
        yn = "y" if cfg["timestamps"] else "n"
        ts = input(f"Timestamps? [{yn}] > ").strip().lower()
        ts = cfg["timestamps"] if ts == "" else ts in ("y", "yes")
        lk = input("Clickable timestamp links? [n] > ").strip().lower() in ("y", "yes")
        sr = input("Write .srt sidecars? [n] > ").strip().lower() in ("y", "yes")
        tr = None
        if input("Transcribe videos without captions (needs GEMINI_API_KEY)? [n] > ").strip().lower() in ("y", "yes"):
            tr = "api"
            if input("Use local whisper.cpp instead of Gemini API? [n] > ").strip().lower() in ("y", "yes"):
                tr = "local"
        sm = input("Summarize each video (needs GEMINI_API_KEY)? [n] > ").strip().lower() in ("y", "yes")
        tl = input("Translate transcripts to (lang code, empty=off) [] > ").strip() or None
        cl = input(f"Cleaning? [{'y' if cfg['clean'] else 'n'}] > ").strip().lower()
        cl = cfg["clean"] if cl == "" else cl in ("y", "yes")
        pdf = input("PDF too? [n] > ").strip().lower() in ("y", "yes")
        ep = input("EPUB too? [n] > ").strip().lower() in ("y", "yes")
        tmp = input(f"Name template [{cfg['template'] or 'layout default'}] > ").strip()
        tmp = tmp or cfg["template"]
        wk = input("Workers [1] > ").strip() or "1"
        try:
            wk = min(4, max(1, int(wk)))
        except ValueError:
            wk = 1
        sp = input("Auto-split words for NotebookLM [0=off] > ").strip() or "0"
        try:
            sp = max(0, int(sp))
        except ValueError:
            sp = 0
        print(f"\n{len(videos)} videos, output: {outdir}/{out}, langs: {lang}, layout: {lay}, "
              f"chunk: {ch}/{chc // 60}min, timestamps: {ts}, template: {tmp or 'default'}, split: {sp or 'off'}")
        go = input("[Enter]=start, q=cancel > ").strip()
        if go.lower() in ("q", "quit"):
            continue
        try:
            run_job(urls, out, lang, max_n, 2.0, False, ch, chc, 1800, videos, outdir, ts, sp,
                    layout=lay, template=tmp, pdf=pdf, epub=ep, since=since, profile=prof, workers=wk,
                    clean=cl, clean_level=cfg["clean_level"],
                    link_timestamps=lk, srt=sr,
                    transcribe=tr is not None, engine=tr or "api",
                    summarize=sm, translate=tl)
        except KeyboardInterrupt:
            print("\nCancelled.")
        again = input("\nNew job? [Enter]=yes, q=quit > ").strip()
        if again.lower() in ("q", "quit", "exit"):
            return
