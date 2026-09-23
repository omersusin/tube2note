"""The download/convert pipeline: per-video fetch and the resumable job runner."""
import datetime
import glob
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor

from yt_dlp import YoutubeDL

from .clean import _clean_text
from .commands import ensure_extra
from .config import _save_last
from .export_srt import segs_to_srt
from .links import linkify
from .llm import (
    _GEMINI_MODEL,
    _gemini_summarize,
    _translate_chunks,
    _try_transcribe,
    _zip_bilingual,
)
from .naming import DEFAULT_TEMPLATES, render_template
from .output import (
    _collection_override,
    _existing_vid,
    _frontmatter,
    _unique_path,
    _video_meta,
    _write_index,
    split_output,
)
from .pdf import md_to_pdf
from .source import _get_vtt, _parse_since, expand, pick_sub
from .store import VID_RE, Store
from .throttle import Bucket, _countdown, _is_throttle, _retry_after_hint
from .ui import dash_end, dash_update, dim, green, log, panel, red, set_verbose
from .vtt import _join_paras, vtt_segments
from .whisper import _local_transcribe


def _srt_text(segs):
    """[(start, text)] -> SRT (end = next start, last = +5s; overlap clamped inside)."""
    triples = [(st, (segs[k + 1][0] if k + 1 < len(segs) else st + 5.0), tx)
               for k, (st, tx) in enumerate(segs)]
    return segs_to_srt(triples)


def _exit_code(result):
    """0 = all videos ok, 1 = partial/none (cron-friendly), 2 = fatal (raised)."""
    if not result or result.get("total", 0) == 0:
        return 1
    return 0 if result.get("skipped", 1) == 0 else 1


def _fetch_unit(ydl_opts, v, langs, ts, bucket, fetch_gap, clean=True,
                clean_level="full", transcribe=False, tmpdir=None, summarize=False,
                gemini_model=_GEMINI_MODEL,
                engine="api", translate=None, bilingual=None, proxy=None, cookiefile=None):
    """One video, network only, never raises (except disk-full).
    Returns dict with stage: extract|subs|fetch|ok."""
    res = {"v": v, "title": v.get("title") or v["id"], "wurl": v.get("url"),
           "channel": v.get("channel"), "lg": None, "auto": False,
           "text": None, "error": None, "throttled": False,
           "stage": "extract", "chapters": [], "meta": {}}
    if bucket is not None:
        bucket.wait()  # pace extract_info too, not just timedtext
    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(v["url"], download=False)
            res["title"] = info.get("title") or res["title"]
            res["wurl"] = info.get("webpage_url") or res["wurl"]
            res["channel"] = res["channel"] or info.get("channel")
            lg, fmts, auto = pick_sub(info, langs)
            if not fmts:
                if transcribe:
                    if engine == "local":
                        ttext, note = _local_transcribe(v["id"], langs[0] if langs else "en",
                                                        tmpdir, proxy=proxy, cookiefile=cookiefile)
                    else:
                        ttext, note = _try_transcribe(v["id"], langs[0] if langs else "en", tmpdir,
                                                      gemini_model, proxy, cookiefile)
                    if ttext is not None:
                        ttext = ttext.strip()
                        if clean:
                            ttext = _clean_text(ttext, langs[0] if langs else "en", clean_level)
                        res.update(lg=langs[0] if langs else "en", auto=False, text=ttext,
                                   trans=True, stage="ok")
                        res["meta"]["method"] = "gemini-transcribe"
                        if summarize and len(ttext.split()) > 100:
                            try:
                                res["summary"] = _gemini_summarize(ttext, res["lg"], gemini_model)
                            except Exception as e:
                                res["summary_error"] = str(e) or type(e).__name__
                        tgt = bilingual or translate
                        if tgt and len(ttext.split()) > 20:
                            try:
                                res["translation"] = _translate_chunks(ttext, tgt,
                                                                       gemini_model)
                            except Exception as e:
                                res["translation_error"] = str(e) or type(e).__name__
                        res["bilingual"] = bool(bilingual)
                        return res
                    res["error"] = f"no subtitles ({note})"
                else:
                    res["error"] = "no subtitles"
                res["stage"] = "subs"
                return res
            res.update(lg=lg, auto=auto)
            res["chapters"] = [(c.get("start_time") or 0, c.get("title") or "")
                               for c in (info.get("chapters") or []) if c.get("title")]
            res["meta"] = _video_meta(info)
            last = None
            for _ in (1, 2):  # ponytail: 60s + ONE retry on 429; hot retries extend the ban
                try:
                    vtt, cached = _get_vtt(v["id"], lg, auto, fmts, ydl.urlopen,
                                          0 if bucket is not None else fetch_gap)
                    segs = vtt_segments(vtt)
                    res["segs"] = segs
                    res["text"] = _join_paras(segs, ts, res["chapters"] or None).strip()
                    if clean:
                        res["text"] = _clean_text(res["text"], lg, clean_level)
                    if summarize and len(res["text"].split()) > 100:
                        try:
                            res["summary"] = _gemini_summarize(res["text"], lg, gemini_model)
                        except Exception as e:
                            res["summary_error"] = str(e) or type(e).__name__
                    tgt = bilingual or translate
                    if tgt and len(res["text"].split()) > 20:
                        try:
                            res["translation"] = _translate_chunks(res["text"], tgt,
                                                                  gemini_model)
                        except Exception as e:
                            res["translation_error"] = str(e) or type(e).__name__
                    res["bilingual"] = bool(bilingual)
                    res["cached"] = cached
                    res["stage"] = "ok"
                    return res
                except Exception as e:
                    last = e
                    if getattr(e, "errno", None) == 28:
                        raise
                    if not _is_throttle(e):
                        break
                    time.sleep(_retry_after_hint(e, 60))
            res["error"] = f"subtitle download failed: {last}"
            res["throttled"] = _is_throttle(last)
            res["hint"] = last
            res["stage"] = "fetch"
            return res
    except Exception as e:
        if getattr(e, "errno", None) == 28:
            raise
        res["error"] = str(e) or type(e).__name__
        res["throttled"] = _is_throttle(e)
        res["hint"] = e
        return res


def _stream(ydl_opts, work, langs, ts, bucket, workers, fetch_gap, clean=True,
            clean_level="full", transcribe=False, tmpdir=None, summarize=False,
            gemini_model=_GEMINI_MODEL, engine="api", translate=None, bilingual=None,
            proxy=None, cookiefile=None):
    """Yield (i, v, res) in submission order; purely serial when workers<=1.
    Parallel submits in small batches so a cooldown stops new work quickly."""
    if workers <= 1:
        for i, v in work:
            yield i, v, _fetch_unit(ydl_opts, v, langs, ts, None, fetch_gap, clean,
                                    clean_level, transcribe, tmpdir, summarize, gemini_model,
                                    engine, translate, bilingual, proxy, cookiefile)
        return
    with ThreadPoolExecutor(max_workers=workers) as ex:
        it = iter(work)
        while True:
            batch = [x for _, x in zip(range(workers), it)]
            if not batch:
                return
            futs = [(i, v, ex.submit(_fetch_unit, ydl_opts, v, langs, ts, bucket, fetch_gap,
                                     clean, clean_level, transcribe, tmpdir, summarize,
                                     gemini_model, engine, translate, bilingual, proxy,
                                     cookiefile)) for i, v in batch]
            for i, v, fu in futs:
                try:
                    yield i, v, fu.result()
                except Exception as e:
                    if getattr(e, "errno", None) == 28:
                        raise
                    yield i, v, {"v": v, "title": v.get("title") or v["id"], "wurl": v.get("url"),
                                 "channel": v.get("channel"), "lg": None, "auto": False,
                                 "text": None, "error": str(e) or type(e).__name__,
                                 "throttled": _is_throttle(e), "hint": e, "stage": "extract",
                                 "chapters": [], "meta": {}}


class _Skip(Exception):
    """A video that must be skipped: carry everything the skip log needs."""

    def __init__(self, title, url, reason, throttled=False):
        super().__init__(reason)
        self.title, self.url, self.reason, self.throttled = title, url, reason, throttled


def _fail(st, todo, words, t0, verbose, throttle_cooldown, hint, sk, status):
    """Record a skip, bump the 5-strike throttle counter, cool down if struck out."""
    st["skip"].append((sk.title, sk.url, sk.reason))
    st["consec"] = st["consec"] + 1 if sk.throttled else 0
    st["status"] = "throttled" if sk.throttled else status
    if st["consec"] >= 5:
        if verbose:
            log("  ! 5 throttles in a row -> long cooldown")
        _countdown(_retry_after_hint(hint, throttle_cooldown),
                   "throttle cooldown", lambda left: dash_update(
            st["ok"] + len(st["skip"]), todo, sk.title, st["ok"], len(st["skip"]), words, t0,
            status=f"throttle cooldown {left // 60:02d}:{left % 60:02d} left"))
        st["consec"], st["status"] = 0, ""


def _chunk_pause(st, todo, title, words, t0, verbose, chunk, chunk_cooldown):
    """Long break every N videos. Returns True if a break was taken."""
    if not (chunk > 0 and st["since_break"] >= chunk and (st["ok"] + len(st["skip"])) < todo):
        return False
    if verbose:
        log(f"--- CHUNK done, {chunk_cooldown // 60} min break ---")
    _countdown(chunk_cooldown, "chunk break", lambda left: dash_update(
        st["ok"] + len(st["skip"]), todo, title, st["ok"], len(st["skip"]), words, t0,
        status=f"chunk break {left // 60:02d}:{left % 60:02d} left"))
    st["status"] = ""
    st["since_break"] = 0
    return True


def _prepare_text(res, v, store, seen_hashes, dedupe, link_timestamps, ts_every, single_line):
    """Fetch-stage gates: dedupe + linkify + thin + single-line.

    Returns (text, plain). Raises _Skip for duplicates (dedupe writes the hash first,
    except too-short texts which run_job skips anyway — never poison future dedupe).
    """
    text = res["text"]
    if text is None:
        return None, None
    if dedupe and text and len(text) >= 50:
        sha = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
        owner = store.hash_owner(sha) if store is not None else seen_hashes.get(sha)
        if owner and owner != v["id"]:
            raise _Skip(res["title"], res["wurl"], f"duplicate transcript of {owner}")
        if store is not None:
            store.note_hash(sha, v["id"])
        else:
            seen_hashes[sha] = v["id"]
    if link_timestamps:
        plain = text  # pre-link snapshot for JSONL
        text = linkify(text, v["id"])
    else:
        plain = text
    if ts_every:
        from .links import thin_markers
        text = thin_markers(text, ts_every)
        plain = thin_markers(plain, ts_every)
    if single_line:
        from .links import to_single_line
        text = to_single_line(text)
        plain = to_single_line(plain)
    return text, plain


def _transblock(text, res, bilingual, translate, verbose):
    """Summary/translation/bilingual block for one video. Pure (no I/O)."""
    out = f"\n### Summary\n{res['summary']}\n" if res.get("summary") else ""
    if res.get("summary_error") and verbose:
        log(f"  ! summary failed: {res['summary_error']}")
    if res.get("translation"):
        if res.get("bilingual"):
            ok, body = _zip_bilingual(text, res["translation"])
            if ok:
                out += f"\n### Bilingual ({bilingual})\n{body}\n"
            else:
                if verbose:
                    log("  ! bilingual paragraph counts differ, falling back to sections")
                out += f"\n### Translation ({bilingual})\n{res['translation']}\n"
        else:
            out += f"\n### Translation ({translate})\n{res['translation']}\n"
    elif res.get("translation_error") and verbose:
        log(f"  ! translation failed: {res['translation_error']}")
    return out


def _write_video(fout, jfh, i, v, title, wurl, lg, auto, text, plain, res, extra,
                 layout, root, out, template, used_paths, obsidian,
                 translate, bilingual, srt, txt, to_stdout, store, verbose):
    """Write one finished video everywhere: merged file, per-video file, sidecars, db.
    Raises OSError outward (caller decides fatal vs broken-pipe). Returns word count."""
    fout.write(f"## {i}. {title}\n\n- Source: {wurl}\n"
               f"- Video ID: {v['id']}\n- Subtitle lang: {lg}"
               f"{' (transcribed)' if res.get('trans') else (' (auto)' if auto else '')}\n"
               f"{extra}\n{text}\n\n---\n\n")
    fout.flush()
    if store is not None:
        store.mark_done(v["id"], title, wurl, len(text.split()))
    if jfh is not None:
        row = {"video_id": v["id"], "title": title, "url": wurl,
               "channel": v.get("channel") or res.get("channel") or "",
               "lang": lg, "text": plain, "words": len(plain.split())}
        jfh.write(json.dumps(row, ensure_ascii=False) + "\n")
        jfh.flush()
    nwords = len(text.split())
    if layout != "single":
        fields = {"channel": v.get("channel") or res.get("channel") or "channel",
                  "title": title or v["id"], "id": v["id"],
                  "index": f"{i:02d}", "date": datetime.date.today().isoformat(),
                  "lang": lg}
        vp = _unique_path(os.path.join(root, render_template(
            template or DEFAULT_TEMPLATES[layout], fields)), v["id"], used_paths)
        if _existing_vid(vp) not in (None, v["id"]):
            # another session's different video owns this path: do not overwrite
            base, ext = os.path.splitext(vp)
            vp = f"{base}_{v['id']}{ext}"
            used_paths.add(vp)
        os.makedirs(os.path.dirname(vp), exist_ok=True)
        with open(vp, "w", encoding="utf-8") as vf:
            vf.write(_frontmatter(title, wurl, v.get("channel") or res.get("channel"),
                                  v["id"], lg, auto, res.get("meta"), obsidian))
            vf.write(f"## {title}\n")
            if res.get("summary"):
                vf.write(f"\n### Summary\n{res['summary']}\n")
            if res.get("translation"):
                if res.get("bilingual"):
                    _bok2, _body2 = _zip_bilingual(text, res["translation"])
                    if _bok2:
                        vf.write(f"\n### Bilingual ({bilingual})\n{_body2}\n")
                    else:
                        if verbose:
                            log("  ! bilingual paragraph counts differ, falling back to sections")
                        vf.write(f"\n### Translation ({bilingual})\n{res['translation']}\n")
                else:
                    vf.write(f"\n### Translation ({translate})\n{res['translation']}\n")
            vf.write(f"\n{text}\n")
    if srt and not to_stdout and res.get("segs"):
        srt_text = _srt_text(res["segs"])
        if layout != "single":
            srt_path = os.path.splitext(vp)[0] + ".srt"
        else:
            base = os.path.splitext(os.path.basename(out))[0]
            srt_path = os.path.join(root, f"{base}_{v['id']}.srt")
        with open(srt_path, "w", encoding="utf-8") as sf:
            sf.write(srt_text)
    elif srt and verbose:
        log("  (no .srt: transcribed videos carry no timings)")
    if txt and not to_stdout:
        from .export_txt import to_txt
        txt_text = to_txt(plain)
        if layout != "single":
            txt_path = os.path.splitext(vp)[0] + ".txt"
        else:
            base = os.path.splitext(os.path.basename(out))[0]
            txt_path = os.path.join(root, f"{base}_{v['id']}.txt")
        with open(txt_path, "w", encoding="utf-8") as tf:
            tf.write(f"{title}\n{v['id']}\n\n{txt_text}")
    return nwords


def _finalize(out, root, layout, videos, completed, words_by_id, store,
              split_words, pdf, epub, st):
    """File mode only: INDEX, skip reconcile, Skipped tail, panels, split/pdf/epub.
    Returns the result dict. Closes the store."""
    try:
        if layout != "single":
            _write_index(root, videos, completed, words_by_id, store.skip_reasons())
            print(f"index: {os.path.join(root, 'INDEX.md')}", flush=True)
        # reconcile skips: drop videos that completed since, so counts/tail stay honest
        for vid in list(completed):
            store.unskip(vid)
        ndone, nskip = store.counts()
        if ndone + nskip >= len(videos):
            if nskip > 0:
                tail_done = False
                try:
                    with open(out, "rb") as _f:
                        _f.seek(max(0, os.path.getsize(out) - 5000))
                        tail_done = b"## Skipped" in _f.read()
                except OSError:
                    pass
                if not tail_done:
                    try:
                        with open(out, "a", encoding="utf-8") as f:
                            f.write("\n## Skipped\n\n")
                            for vid, title, url, reason in store.skips():
                                f.write(f"- [{title or '?'}]({url or ''}) — {reason}\n")
                    except OSError:
                        pass
            dash_end()
            print(panel("Done", [
                f"{green(str(ndone))} videos -> {out} ({nskip} skipped)",
                f"~{st['words']} words this run",
            ]))
            if split_words > 0:
                with open(out, encoding="utf-8") as _rf:
                    total_words = len(_rf.read().split())
                if total_words > split_words:
                    parts = split_output(out, split_words)
                    if len(parts) > 1:
                        print(panel("Upload to NotebookLM", ["Add each part as a separate source:"]
                                    + [f"  {j}. {p}" for j, p in enumerate(parts, 1)]))
                    else:
                        print(f"Single file is enough ({total_words} words).")
                else:
                    print(f"No split needed ({total_words} words <= {split_words}).")
            else:
                print("Upload to NotebookLM: add this file as a source.")
                print(dim("Cap is 500,000 words/file — use --split-words if bigger."))
            if pdf:
                base, _ = os.path.splitext(out)
                for src in [out] + sorted(glob.glob(base + "_part*.md")):
                    try:
                        print("PDF: " + md_to_pdf(src), flush=True)
                    except SystemExit as e:
                        print(e)
                        break
            if epub:
                from .epub import md_to_epub
                base, _ = os.path.splitext(out)
                for src in [out] + sorted(glob.glob(base + "_part*.md")):
                    try:
                        print("EPUB: " + md_to_epub(src), flush=True)
                    except OSError as e:
                        print(f"! EPUB failed: {e}")
                        break
        else:
            dash_end()
            print(f"Checkpoint: {st['ok']} videos, {st['words']} words -> {out} (total: {ndone}/{len(videos)})")
        return {"ok": st["ok"], "skipped": nskip, "total": len(videos)}
    finally:
        try:
            store.close()
        except Exception:
            pass


def _open_collection(out, fresh, to_stdout, jsonl, total, langs, layout, chunk, chunk_cooldown, _say):
    """Open output handles + resume store. Returns a dict. Raises OSError outward."""
    done_log, skip_log = out + ".done", out + ".skip"
    store = None
    if not to_stdout:
        store = Store(out + ".db")
        if fresh:
            try:
                store.cx.execute("DELETE FROM videos")
                store.cx.execute("DELETE FROM hashes")
                store.cx.commit()
            except Exception:
                pass
        elif store.import_sidecars(done_log, skip_log):
            _say("migrated legacy .done/.skip into resume database", flush=True)
        done = set() if fresh else store.done_ids()
        if done:
            _say(f"resuming: {len(done)} videos already done", flush=True)
    else:
        done = set()
    fresh_start = fresh or (not to_stdout and not os.path.exists(out))
    mode = "w" if fresh_start else "a"
    fout = None
    jfh = None
    try:
        fout = sys.stdout if to_stdout else open(out, mode, encoding="utf-8")  # never closed (see finally)
        if jsonl and not to_stdout:
            jpath = out + ".jsonl"
            if fresh_start:
                try:
                    os.remove(jpath)
                except OSError:
                    pass
            elif done and not os.path.exists(jpath):
                _say("warning: .jsonl missing but videos already done — rows incomplete, use --fresh",
                      file=sys.stderr, flush=True)
            jfh = open(jpath, "a", encoding="utf-8")
        if fresh_start:
            done = set()
        if mode == "w" and not to_stdout:
            today = datetime.date.today().isoformat()
            fout.write(f"# YouTube Research Notes\n\n- Date: {today}\n- Videos: target {total}\n"
                       f"- Languages: {','.join(langs)}\n\nFeed this file to NotebookLM as a source.\n\n---\n\n")
    except Exception:
        try:
            if fout is not None and fout is not sys.stdout:
                fout.close()
        except Exception:
            pass
        try:
            if jfh is not None:
                jfh.close()
        except Exception:
            pass
        try:
            if store is not None:
                store.close()
        except Exception:
            pass
        raise
    todo = max(0, total - len(done))
    _say(f"target: {todo} videos (chunk: {chunk}, chunk break: {chunk_cooldown // 60} min, layout: {layout})",
         flush=True)
    return {"store": store, "fout": fout, "jfh": jfh, "done": done,
            "completed": set(done),
            "words_by_id": {} if (fresh_start or to_stdout) else store.words_map(),
            "todo": todo, "fresh_start": fresh_start, "mode": mode}


def run_job(urls, out, lang_str, max_n, sleep, fresh=False, chunk=50, chunk_cooldown=600,
            throttle_cooldown=1800, videos=None, outdir=".", ts=False, split_words=0,
            verbose=False, layout="single", template="", pdf=False,
            proxy=None, cookiefile=None, since=None, profile=None, fetch_gap=10,
            workers=1, clean=True, clean_level="full", transcribe=False, summarize=False,
            gemini_model=_GEMINI_MODEL, engine="api", translate=None, bilingual=None, auto_yes=False,
            link_timestamps=False, srt=False, epub=False, dedupe=True, obsidian=False,
            ts_every=0, single_line=False, txt=False,
            cookies_from_browser=None, jsonl=False):
    to_stdout = (out == "-")
    _say = (lambda *a, **k: print(*a, **{**k, "file": sys.stderr, "flush": True})) \
        if to_stdout else (lambda *a, **k: print(*a, **k))
    if to_stdout:  # pipe mode: data on stdout, everything else on stderr, no files/db
        from .ui import set_pipe
        set_pipe(True)
        set_verbose(False)
        verbose = False
        layout = "single"
        try:
            sys.stdout.reconfigure(errors="replace")
        except Exception:
            pass
    if videos is None:
        videos = None
        if since and len(urls) == 1:  # fast path: channel RSS avoids the full listing
            try:
                from .source import rss_videos
                videos = rss_videos(urls[0], _parse_since(since), max_n,
                                    cookies_from_browser=cookies_from_browser)
                if videos is not None:
                    _say(f"list from RSS ({len(videos)} videos since {since})", flush=True)
            except Exception:
                videos = None
        if videos is None:
            videos, _ = expand(urls, max_n, since, cookies_from_browser=cookies_from_browser)
    if outdir and outdir != "." and not to_stdout:
        outdir = os.path.expanduser(outdir)
        os.makedirs(outdir, exist_ok=True)
        out = os.path.join(outdir, out)
    root = os.path.dirname(os.path.abspath(out)) if not to_stdout else ""
    coll = {}
    if not to_stdout:
        coll = _collection_override(root)
        if coll.get("layout") in ("single", "videos", "tree"):
            layout = coll["layout"]
        if isinstance(coll.get("lang"), str) and coll["lang"].strip():
            lang_str = coll["lang"]
        if isinstance(coll.get("timestamps"), bool):
            ts = coll["timestamps"]
        if coll.get("chunk") is not None:
            try:
                chunk = max(0, int(coll["chunk"]))
            except (ValueError, TypeError):
                pass
        if coll.get("chunk_cooldown_min") is not None:  # minutes, like the TUI prompt
            try:
                chunk_cooldown = max(0, int(coll["chunk_cooldown_min"])) * 60
            except (ValueError, TypeError):
                pass
    ts = ts or link_timestamps  # links need markers; never silently produce unlinkable text
    langs = [s.strip() for s in lang_str.split(",") if s.strip()]
    total = len(videos)
    if transcribe and not os.environ.get("GEMINI_API_KEY", "") and engine != "local":
        _say("transcribe needs GEMINI_API_KEY (free at aistudio.google.com) — stopping before any work.")
        return {"ok": 0, "skipped": 0, "total": total}
    if transcribe and engine == "local" and not ensure_extra("whisper", auto_yes):
        _say("local transcription unavailable — stopping before any work.")
        return {"ok": 0, "skipped": 0, "total": total}
    if summarize and not os.environ.get("GEMINI_API_KEY", ""):
        _say("summarize needs GEMINI_API_KEY (free at aistudio.google.com) — stopping before any work.")
        return {"ok": 0, "skipped": 0, "total": total}
    if (transcribe or summarize or translate or bilingual) and os.environ.get("GEMINI_API_KEY", ""):
        _say("notice: transcripts/summaries will be sent to the Google Gemini API.", flush=True)
    if not to_stdout:  # a stdout job has no resumable artifact; saving out="-" would poison --resume-last
        _save_last(urls=urls, out=os.path.basename(out),
                   outdir=os.path.dirname(os.path.abspath(out)) or ".", lang=lang_str,
                   max_n=max_n, chunk=chunk, chunk_cooldown=chunk_cooldown,
                   throttle_cooldown=throttle_cooldown, layout=layout,
                   template=template, ts=ts, split_words=split_words, sleep=sleep,
                   since=since, proxy=proxy, cookiefile=cookiefile, profile=profile,
                   translate=translate, clean=clean, clean_level=clean_level,
                   transcribe=transcribe, summarize=summarize, gemini_model=gemini_model,
                    engine=engine, fetch_gap=fetch_gap, workers=workers, pdf=pdf,
                link_timestamps=link_timestamps, srt=srt, epub=epub, dedupe=dedupe,
                ts_every=ts_every, single_line=single_line, txt=txt,
                obsidian=obsidian, cookies_from_browser=cookies_from_browser, jsonl=jsonl,
                bilingual=bilingual)
    _say(f"{total} videos found", flush=True)
    if not videos:
        return {"ok": 0, "skipped": 0, "total": 0}
    oc = _open_collection(out, fresh, to_stdout, jsonl, total, langs, layout,
                          chunk, chunk_cooldown, _say)
    store, fout, jfh = oc["store"], oc["fout"], oc["jfh"]
    done, completed, words_by_id = oc["done"], oc["completed"], oc["words_by_id"]
    todo = oc["todo"]
    try:
        st = {"ok": 0, "skip": [], "words": 0, "consec": 0, "since_break": 0, "status": ""}
        seen_hashes = {}  # pipe-mode in-process dedupe (no db there)
        used_paths = set()
        set_verbose(verbose)
        t0 = time.time()
        ydl_opts = {"quiet": True, "no_warnings": True, "skip_download": True,
                    "writesubtitles": False, "socket_timeout": 20,
                    "subtitlesformat": "vtt/best",
                    "extractor_args": {"youtube": {"skip": ["translated_subs"]}}}
        if proxy:
            ydl_opts["proxy"] = proxy
        if cookiefile:
            ydl_opts["cookiefile"] = os.path.expanduser(cookiefile)
        if cookies_from_browser:
            ydl_opts["cookiesfrombrowser"] = cookies_from_browser
        bucket = Bucket(rate=0.15, capacity=2) if workers > 1 else None
        work = [(i, v) for i, v in enumerate(videos, 1) if v["id"] not in done]
        tmpdir = tempfile.mkdtemp(prefix="tube2note-")
        if workers > 1:
            _say(f"parallel mode: {workers} workers sharing one bucket (~1 fetch/7s)", flush=True)
        with YoutubeDL(ydl_opts):
            for i, v, res in _stream(ydl_opts, work, langs, ts, bucket, workers, fetch_gap,
                                    clean, clean_level, transcribe, tmpdir, summarize, gemini_model,
                                    engine, translate, bilingual, proxy, cookiefile):
                _chunk_pause(st, todo, v["title"], st["words"], t0, verbose, chunk, chunk_cooldown)
                st["since_break"] += 1
                dash_update(st["ok"] + len(st["skip"]), todo, f"[{i}/{total}] {v['title']}",
                            st["ok"], len(st["skip"]), st["words"], t0, st["status"])
                if verbose:
                    log(f"[{i}/{total}] {v['title'][:70]}")
                if res["stage"] == "extract":
                    if verbose:
                        log(f"  ! skipped: {res['error']}")
                    _fail(st, todo, st["words"], t0, verbose, throttle_cooldown,
                          res.get("hint") or res.get("error") or "",
                          _Skip(v["title"], v["url"], res["error"], res["throttled"]),
                          "extract failed")
                    continue
                title, wurl, lg, auto = res["title"], res["wurl"], res["lg"], res["auto"]
                if res["stage"] == "subs":
                    if verbose:
                        log("  ! no subtitles, skipped")
                    _fail(st, todo, st["words"], t0, verbose, throttle_cooldown, "",
                          _Skip(title, wurl, "no subtitles"), "no subtitles")
                    continue
                try:
                    text, plain = _prepare_text(res, v, store, seen_hashes, dedupe,
                                                link_timestamps, ts_every, single_line)
                except _Skip as sk:
                    _fail(st, todo, st["words"], t0, verbose, throttle_cooldown, "", sk, "duplicate")
                    continue
                if res.get("cached") and verbose:
                    log("  (from cache)")
                if text is None:
                    if verbose:
                        log(f"  ! subtitle download failed: {res['error']}")
                    _fail(st, todo, st["words"], t0, verbose, throttle_cooldown,
                          res.get("hint") or res.get("error") or "",
                          _Skip(title, wurl, res["error"], res["throttled"]), "subtitle failed")
                    continue
                st["consec"], st["status"] = 0, ""
                if len(text) < 50:
                    _fail(st, todo, st["words"], t0, verbose, throttle_cooldown, "",
                          _Skip(title, wurl, "subtitle too short"), "subtitle too short")
                    continue
                extra = _transblock(text, res, bilingual, translate, verbose)
                try:
                    nwords = _write_video(fout, jfh, i, v, title, wurl, lg, auto, text, plain, res,
                                          extra, layout, root, out, template, used_paths, obsidian,
                                          translate, bilingual, srt, txt, to_stdout, store, verbose)
                    st["words"] += nwords
                    st["ok"] += 1
                    completed.add(v["id"])
                    done.add(v["id"])
                    words_by_id[v["id"]] = nwords
                except OSError as e:
                    if to_stdout and isinstance(e, BrokenPipeError):
                        os._exit(0)  # `| head` is success, not failure
                    _say(red(f"  ! FATAL disk/IO error, stopping: {e}"))
                    raise SystemExit(1)
                dash_update(st["ok"] + len(st["skip"]), todo, v["title"], st["ok"], len(st["skip"]),
                            st["words"], t0)
                time.sleep(sleep)
        dash_update(todo, todo, "done", st["ok"], len(st["skip"]), st["words"], t0)
        dash_end()
        for t, u, s in st["skip"]:
            if store is not None:
                vid = (VID_RE.search(u or "") or [None, u])[1]
                store.mark_skip(vid or u, t, u, s)
        if not to_stdout:
            fout.close()
        shutil.rmtree(tmpdir, ignore_errors=True)
    finally:  # Ctrl+C / SystemExit mid-run: never leak handles or temp audio
        try:
            if fout is not None and fout is not sys.stdout:
                fout.close()
        except Exception:
            pass
        try:
            if jfh is not None:
                jfh.close()
        except Exception:
            pass
        try:
            shutil.rmtree(tmpdir, ignore_errors=True)
        except NameError:
            pass
        try:
            if sys.exc_info()[0] is not None and store is not None:
                try:
                    store.close()
                except Exception:
                    pass
        except NameError:
            pass
        from .ui import set_pipe as _set_pipe
        _set_pipe(False)  # never leak pipe mode into in-process callers
    if to_stdout:
        _say(f"{st['ok']}/{len(videos)} videos, {st['words']} words (stdout)")
        return {"ok": st["ok"], "skipped": len(st["skip"]), "total": len(videos)}
    return _finalize(out, root, layout, videos, completed, words_by_id, store,
                     split_words, pdf, epub, st)
