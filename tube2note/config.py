"""Config file, profiles, env vars and last-job resume info."""
import json
import os


def is_first_run():
    p = os.path.expanduser("~/.config/yt2md/seen")
    if os.path.exists(p):
        return False
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "w").write("1")
    except OSError:
        return False
    return True


CONFIG_PATH = os.path.expanduser("~/.config/yt2md/config.json")


DEFAULTS = {"outdir": ".", "layout": "single", "timestamps": False, "chunk": 50,
            "chunk_cooldown_min": 10, "lang": "tr,en", "template": "", "clean": True}


ENV_MAP = {"outdir": "YT2MD_OUTDIR", "layout": "YT2MD_LAYOUT", "lang": "YT2MD_LANG",
           "chunk": "YT2MD_CHUNK", "timestamps": "YT2MD_TIMESTAMPS",
           "chunk_cooldown_min": "YT2MD_COOLDOWN_MIN", "template": "YT2MD_TEMPLATE",
           "clean": "YT2MD_CLEAN"}


def load_config():
    """Config file: {"defaults": {...}, "profiles": {name: {...}}}. Old flat files count as defaults."""
    raw = {}
    try:
        data = json.load(open(CONFIG_PATH, encoding="utf-8"))
        if isinstance(data, dict):
            raw = data
    except (OSError, ValueError, TypeError):
        pass
    if "defaults" in raw or "profiles" in raw:
        defaults, profiles = raw.get("defaults") or {}, raw.get("profiles") or {}
    else:
        defaults, profiles = raw, {}
    if not isinstance(defaults, dict):
        defaults = {}
    if not isinstance(profiles, dict):
        profiles = {}
    store = {"defaults": defaults, "profiles": profiles}
    for k, v in raw.items():  # keep runtime keys like "last", "last:<profile>"
        if k not in store:
            store[k] = v
    return store


def save_config(store):
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    json.dump(store, open(CONFIG_PATH, "w", encoding="utf-8"), indent=2)


def _merge(base, store, profile, flags, env):
    """Precedence: flags > env > profile > config defaults > builtins. Pure (testable)."""
    cfg = dict(base)
    cfg.update({k: v for k, v in store.get("defaults", {}).items() if k in base})
    if profile and profile in store.get("profiles", {}):
        cfg.update({k: v for k, v in store["profiles"][profile].items() if k in base})
    for key, var in ENV_MAP.items():
        if env.get(var, "") != "":
            cfg[key] = env[var]
    cfg.update({k: v for k, v in flags.items() if v is not None})
    for key in ("chunk", "chunk_cooldown_min"):
        try:
            cfg[key] = max(0, int(cfg[key]))
        except (ValueError, TypeError):
            cfg[key] = base[key]
    for key in ("timestamps", "clean"):
        if isinstance(cfg.get(key), str):
            cfg[key] = cfg[key].lower() in ("1", "y", "yes", "true")
    if cfg.get("layout") not in ("single", "videos", "tree"):
        cfg["layout"] = base["layout"]
    return cfg


def resolve_config(flags=None, profile=None):
    return _merge(dict(DEFAULTS), load_config(), profile, flags or {}, dict(os.environ))


def _save_last(profile=None, **kw):
    try:
        store = load_config()
        store["last:" + profile if profile else "last"] = kw
        save_config(store)
    except OSError:
        pass
