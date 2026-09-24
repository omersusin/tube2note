#!/bin/sh
# tube2note universal installer: curl -fsSL https://omersusin.github.io/tube2note/install.sh | sh
# Detects platform, asks app-vs-CLI, installs, verifies. POSIX sh, no bashisms.
set -u
REPO="omersusin/tube2note"
BIN_DIR="${HOME}/.local/bin"
NONINTERACTIVE="${NONINTERACTIVE:-}"

say() { printf '%s\n' "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

# --- detect platform ---
OS="$(uname -s 2>/dev/null || echo unknown)"
ARCH="$(uname -m 2>/dev/null || echo unknown)"
IS_TERMUX=""
[ -n "${PREFIX:-}" ] && [ -d "${PREFIX:-/nonexistent}/bin" ] && case "$OS" in Linux) IS_TERMUX=1;; esac
[ "$(uname -o 2>/dev/null || echo '')" = "Android" ] && IS_TERMUX=1

case "$ARCH" in x86_64|amd64) MARCH="x64";; aarch64|arm64) MARCH="arm64";; *) MARCH="$ARCH";; esac

ask() { # ask <prompt> <default:Y/N> -> 0 yes / 1 no
    if [ -n "$NONINTERACTIVE" ] || [ ! -t 0 ]; then [ "$2" = "Y" ]; return; fi
    printf '%s [%s/%s]: ' "$1" "$([ "$2" = Y ] && echo Y || echo y)" "$([ "$2" = Y ] && echo n || echo N)" >/dev/tty
    read -r ans </dev/tty || ans=""
    case "$ans" in "" ) [ "$2" = "Y" ];; [Yy]*) true;; *) false;; esac
}

need() { command -v "$1" >/dev/null 2>&1 || die "need '$1' (install python3 first)"; }

install_cli() {
    need python3
    TAG="$(latest_tag || true)"
    SPEC="tube2note"
    case "$TAG" in v*) SPEC="tube2note==${TAG#v}";; esac
    if command -v pipx >/dev/null 2>&1; then
        pipx install "$SPEC" || pipx reinstall "$SPEC" || die "install failed (see error above)"
    elif python3 -m pip --version >/dev/null 2>&1; then
        python3 -m pip install --user --no-cache-dir -U "$SPEC" || die "install failed (see error above — on Termux, try: pkg install clang)"
    else
        die "no pip found (try: pkg install python / apt install python3-pip)"
    fi
    case ":${PATH}:" in *":${BIN_DIR}:"*) ;; *)
        say "Add to PATH: export PATH=\"\$HOME/.local/bin:\$PATH\""
    esac
    if command -v tube2note >/dev/null 2>&1; then
        tube2note --self-test >/dev/null 2>&1 && say "OK: tube2note installed" || say "installed (self-test needs network once)"
    else
        say "installed; restart shell or fix PATH, then run: tube2note --help"
    fi
}

latest_tag() { # via GitHub API, needs curl
    curl -fsSL "https://api.github.com/repos/${REPO}/releases/latest" 2>/dev/null \
        | grep -m1 '"tag_name"' | cut -d'"' -f4
}

apk_for_arch() { # print asset download URL matching arch, or empty
    tag="$1"
    curl -fsSL "https://api.github.com/repos/${REPO}/releases/tags/${tag}" 2>/dev/null \
        | grep '"browser_download_url"' | cut -d'"' -f4 | grep -i "\.apk$" | head -1
}

app_asset() { # print best desktop asset URL for OS/ARCH, or empty
    tag="$1"
    assets="$(curl -fsSL "https://api.github.com/repos/${REPO}/releases/tags/${tag}" 2>/dev/null \
        | grep '"browser_download_url"' | cut -d'"' -f4)"
    [ -z "$assets" ] && return 1
    case "$OS" in
        Linux) echo "$assets" | grep -iE "\.AppImage$|\.deb$" | head -1;;
        Darwin) case "$MARCH" in arm64) echo "$assets" | grep -iE "aarch64.*\.dmg$|arm64.*\.dmg$" | head -1;; *) echo "$assets" | grep -iE "x64.*\.dmg$" | head -1;; esac;;
    esac
}

install_app() {
    need curl
    TAG="$(latest_tag || true)"
    [ -z "$TAG" ] && die "cannot reach GitHub API (network? try CLI instead)"
    say "latest: $TAG"
    if [ -n "$IS_TERMUX" ]; then
        URL="$(apk_for_arch "$TAG")"
        [ -z "$URL" ] && die "no APK on release $TAG — see https://github.com/${REPO}/releases/tag/${TAG}"
        OUT="${HOME}/storage/downloads/$(basename "$URL")"
        mkdir -p "${HOME}/storage/downloads"
        say "downloading $(basename "$URL") ..."
        curl -fSL -o "$OUT" "$URL" || die "download failed"
        say "saved to Downloads. Open it to install (allow unknown apps once)."
        return
    fi
    URL="$(app_asset "$TAG")"
    [ -z "$URL" ] && die "no desktop build for $OS/$MARCH on $TAG — see https://github.com/${REPO}/releases/tag/${TAG}"
    mkdir -p "${HOME}/Downloads"
    say "downloading $(basename "$URL") ..."
    curl -fSL -o "${HOME}/Downloads/$(basename "$URL")" "$URL" || die "download failed"
    say "saved to ~/Downloads/$(basename "$URL")"
}

say "tube2note installer ($OS/$MARCH${IS_TERMUX:+ termux})"
if [ -n "$IS_TERMUX" ]; then
    Q="Install the Android app (APK) or the CLI? [app/CLI]"
else
    Q="Install the desktop app instead of the CLI?"
fi
if [ -n "$NONINTERACTIVE" ]; then
    install_cli
elif [ -r /dev/tty ] && [ -w /dev/tty ]; then
    if [ -n "$IS_TERMUX" ]; then
        if printf '%s ' "$Q" >/dev/tty 2>/dev/null && read -r ans </dev/tty 2>/dev/null; then
            case "$ans" in [Aa]*) install_app;; *) install_cli;; esac
        else
            install_cli
        fi
    elif ask "$Q" N; then
        install_app
    else
        install_cli
    fi
else
    install_cli
fi
say "done. Quick start: tube2note 'https://youtu.be/...' -o notes.md"
