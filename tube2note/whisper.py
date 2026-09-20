"""Offline transcription via whisper.cpp (optional extra)."""
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
    r = subprocess.run(["curl", "-L", "-o", p, WHISPER_MODEL_URLS[name]],
                       capture_output=True, text=True)
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


def _local_transcribe(vid, lang, tmpdir, model="tiny", auto_yes=False):
    """Captionless fallback via external whisper.cpp. Returns (text, note) or (None, reason)."""
    import subprocess
    binary, hint = find_whisper()
    if not binary:
        return None, f"whisper.cpp not found ({hint})"
    if not shutil.which("ffmpeg"):
        return None, "needs ffmpeg (pkg install ffmpeg) for 16kHz WAV"
    model_path = ensure_whisper_model(model, auto_yes)
    if not model_path:
        return None, "whisper model missing"
    path, ext = _download_audio(vid, tmpdir)
    if path is None:
        return None, ext
    try:
        wav = os.path.join(tmpdir, vid + "_16k.wav")
        r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", path,
                            "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", wav],
                           capture_output=True, text=True, timeout=300)
        if r.returncode != 0 or not os.path.exists(wav):
            return None, "ffmpeg convert failed"
        stem = os.path.join(tmpdir, vid + "_stt")
        r = subprocess.run([binary, "-m", model_path, "-f", wav, "-l", lang,
                            "-t", "2", "-ng", "-otxt", "-of", stem, "-np"],
                           capture_output=True, text=True, timeout=1800)
        out = stem + ".txt"
        if r.returncode != 0 or not os.path.exists(out):
            return None, "whisper.cpp failed"
        text = open(out, encoding="utf-8").read().strip()
        if len(text) < 50:
            return None, "transcript too short"
        return text, f"transcribed locally (whisper.cpp {model})"
    finally:
        for f in (path, os.path.join(tmpdir, vid + "_16k.wav"),
                  os.path.join(tmpdir, vid + "_stt.txt")):
            try:
                os.remove(f)
            except OSError:
                pass
