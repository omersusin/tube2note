"""Offline transcription via whisper.cpp (optional extra)."""
import json
import os
import shutil

from .llm import _download_audio

WHISPER_MODEL_URLS = {
    "tiny": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-tiny.bin",
    "base": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin",
}


WHISPER_MODEL_SIZES = {"tiny": 75000000, "base": 142000000}


def find_whisper():
    """(binary_path or None, hint). Checks env, PATH, ~/whisper.cpp build."""
    cands = [os.environ.get("WHISPER_CLI", ""),
             shutil.which("whisper-cli") or "",
             os.path.expanduser("~/whisper.cpp/build/bin/whisper-cli")]
    for p in cands:
        if p and os.path.isfile(p) and os.access(p, os.X_OK):
            return p, ""
    legacy = os.path.expanduser("~/whisper.cpp/build/bin/main")
    if os.path.isfile(legacy) and os.access(legacy, os.X_OK):
        return legacy, ""
    return None, "build whisper.cpp (cmake, GGML_NO_OPENMP=ON on Termux) or set WHISPER_CLI"


def whisper_model_path(name="tiny"):
    d = os.path.join(os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")),
                     "tube2note", "models")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, f"ggml-{name}.bin")


def ensure_whisper_model(name="tiny", auto_yes=False):
    if name not in WHISPER_MODEL_URLS:
        print(f"unknown whisper model '{name}' (available: {', '.join(sorted(WHISPER_MODEL_URLS))})")
        return None
    p = whisper_model_path(name)
    if os.path.exists(p):
        _check_model_size(p, name)
        return p
    print(f"Whisper model '{name}' (~{'75' if name == 'tiny' else '142'}MB) is missing.")
    if not auto_yes:
        try:
            ans = input("Download it now? [y/N] > ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            return None
        if ans not in ("y", "yes"):
            return None
    import subprocess
    print(f"Downloading {name} model...")
    try:
        r = subprocess.run(["curl", "-L", "-o", p, WHISPER_MODEL_URLS[name]],
                           capture_output=True, text=True)
    except (FileNotFoundError, subprocess.SubprocessError) as e:
        print(f"No curl ({e}). Get it manually: {WHISPER_MODEL_URLS[name]} -> {p}")
        return None
    if r.returncode != 0 or not os.path.exists(p):
        print(f"Model download failed. Get it manually: {WHISPER_MODEL_URLS[name]}")
        return None
    _check_model_size(p, name)
    return p


def _check_model_size(p, name):
    """Warn (don't block) if a model file is far from its expected size."""
    try:
        exp = WHISPER_MODEL_SIZES.get(name, 0)
        got = os.path.getsize(p)
        if exp and abs(got - exp) / exp > 0.3:
            print(f"warning: {p} is {got} bytes, expected ~{exp} — may be corrupt, re-download if STT fails.")
    except OSError:
        pass


def _whisper_ts_to_secs(s, prev=0.0):
    """'HH:MM:SS,mmm' / 'HH:MM:SS.mmm' / secs -> float; garbage keeps prev."""
    try:
        s = str(s or "").strip().replace(",", ".")
        p = s.split(":")
        if len(p) == 3:
            return int(p[0]) * 3600 + int(p[1]) * 60 + float(p[2])
        if len(p) == 2:
            return int(p[0]) * 60 + float(p[1])
        return float(s)
    except (ValueError, IndexError, AttributeError):
        return prev


def _parse_whisper_json(data):
    """whisper.cpp -oj output -> [(start_secs, text)]. Tolerant of schema drift.

    Handles {'transcription': [{timestamps/offsets, text}]} and
    {'segments': [{start/t0/from, text}]} shapes; per-word entries ignored.
    """
    segs = []
    items = []
    if isinstance(data, dict):
        items = data.get("segments") or data.get("transcription") or []
    elif isinstance(data, list):
        items = data
    for it in items:
        if not isinstance(it, dict):
            continue
        text = (it.get("text") or "").strip()
        if not text:
            continue
        st = segs[-1][0] if segs else 0.0
        if "start" in it:
            try:
                st = float(it["start"])
            except (TypeError, ValueError):
                st = segs[-1][0] if segs else 0.0
        elif "t0" in it:
            try:
                st = float(it["t0"]) / 100.0  # centiseconds in some builds
            except (TypeError, ValueError):
                st = segs[-1][0] if segs else 0.0
        elif isinstance(it.get("timestamps"), dict):
            ts = it["timestamps"]
            st = _whisper_ts_to_secs(ts.get("from"), segs[-1][0] if segs else 0.0)
        elif isinstance(it.get("offsets"), dict):
            try:
                st = float(it["offsets"].get("from", 0)) / 1000.0
            except (TypeError, ValueError):
                st = segs[-1][0] if segs else 0.0
        elif "from" in it:
            v = it["from"]
            if isinstance(v, str):
                st = _whisper_ts_to_secs(v, segs[-1][0] if segs else 0.0)
            else:
                try:
                    st = float(v or 0) / 1000.0
                except (TypeError, ValueError):
                    st = segs[-1][0] if segs else 0.0
        if segs and segs[-1][1] == text:
            continue  # drop back-to-back dupes, like vtt_segments
        segs.append((st, text))
    return segs


def whisper_segments(vid, lang, tmpdir, model="tiny", auto_yes=False,
                     proxy=None, cookiefile=None):
    """Captionless fallback via external whisper.cpp, with word-timestamped segments.

    Runs whisper.cpp with -otxt -ovtt --output-json and parses the segments
    json (word offsets kept in the file, [(start, text)] returned).
    Returns (text, segs, note) or (None, [], reason). New callers only;
    old 2-tuple callers keep using _local_transcribe.
    """
    import subprocess
    binary, hint = find_whisper()
    if not binary:
        return None, [], f"whisper.cpp not found ({hint})"
    if not shutil.which("ffmpeg"):
        return None, [], "needs ffmpeg (pkg install ffmpeg) for 16kHz WAV"
    model_path = ensure_whisper_model(model, auto_yes)
    if not model_path:
        return None, [], "whisper model missing"
    path, ext = _download_audio(vid, tmpdir, proxy=proxy, cookiefile=cookiefile)
    if path is None:
        return None, [], ext
    try:
        wav = os.path.join(tmpdir, vid + "_16k.wav")
        r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", path,
                            "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", wav],
                           capture_output=True, text=True, timeout=300)
        if r.returncode != 0 or not os.path.exists(wav):
            return None, [], "ffmpeg convert failed"
        stem = os.path.join(tmpdir, vid + "_stt")
        r = subprocess.run([binary, "-m", model_path, "-f", wav, "-l", lang,
                            "-t", "2", "-ng", "-otxt", "-ovtt", "-oj", "-of", stem, "-np"],
                           capture_output=True, text=True, timeout=1800)
        out = stem + ".txt"
        if r.returncode != 0 or not os.path.exists(out):
            return None, [], "whisper.cpp failed"
        try:
            with open(out, encoding="utf-8") as f:
                text = f.read().strip()
        except OSError:
            return None, [], "whisper.cpp failed"
        if len(text) < 50:
            return None, [], "transcript too short"
        segs = []
        try:
            with open(stem + ".json", encoding="utf-8") as f:
                segs = _parse_whisper_json(json.load(f))
        except (OSError, ValueError):
            segs = []
        return text, segs, f"transcribed locally (whisper.cpp {model})"
    finally:
        for f in (path, os.path.join(tmpdir, vid + "_16k.wav"),
                  os.path.join(tmpdir, vid + "_stt.txt"),
                  os.path.join(tmpdir, vid + "_stt.vtt"),
                  os.path.join(tmpdir, vid + "_stt.json")):
            try:
                os.remove(f)
            except OSError:
                pass


def _local_transcribe(vid, lang, tmpdir, model="tiny", auto_yes=False,
                      proxy=None, cookiefile=None):
    """Captionless fallback via external whisper.cpp. Returns (text, note) or (None, reason)."""
    text, _segs, note = whisper_segments(vid, lang, tmpdir, model, auto_yes, proxy, cookiefile)
    if text is None:
        return None, note
    return text, note
