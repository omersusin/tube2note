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
    if command -v pipx >/dev/null 2>&1; then
        pipx install 'tube2note' || pipx reinstall 'tube2note' || die "install failed (see error above)"
    elif python3 -m pip --version >/dev/null 2>&1; then
        python3 -m pip install --user -U 'tube2note' || die "install failed (see error above — on Termux, try: pkg install clang)"
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

install_app() {
    need curl
    TAG="$(latest_tag || true)"
    [ -z "$TAG" ] && die "cannot reach GitHub API (network? try CLI instead)"
    say "latest: $TAG"
    if [ -n "$IS_TERMUX" ]; then
        say "On Android grab the APK:"
        say "  https://github.com/${REPO}/releases/download/${TAG}/tube2note-${MARCH}.apk"
        say "(asset name varies; pick your arch from the release page)"
        return
    fi
    case "$OS" in
        Linux) ASSET="tube2note-${TAG}-linux-x86_64.AppImage";;
        Darwin) ASSET="tube2note-${TAG}-macos.dmg";;
        *) say "No desktop build for $OS — use the release page:"; say "  https://github.com/${REPO}/releases/tag/${TAG}"; return;;
    esac
    URL="https://github.com/${REPO}/releases/download/${TAG}/${ASSET}"
    say "fetching $ASSET ..."
    curl -fSL -o "${HOME}/Downloads/${ASSET}" "$URL" && say "saved to ~/Downloads/${ASSET}" \
        || say "asset not found (name differs?) — see https://github.com/${REPO}/releases/tag/${TAG}"
}

say "tube2note installer ($OS/$MARCH${IS_TERMUX:+ termux})"
if [ -z "$IS_TERMUX" ] && ask "Install the desktop app instead of the CLI?" N; then
    install_app
else
    install_cli
fi
say "done. Quick start: tube2note 'https://youtu.be/...' -o notes.md"
