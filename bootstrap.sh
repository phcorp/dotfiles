#!/bin/sh
# Download this file for review, then run it; no remote script is piped into a shell.
set -eu
umask 077
mode=interactive
dependencies_only=0
profiles=shell
sync=0
for arg in "$@"; do
    case $arg in
        --non-interactive) mode=non-interactive ;;
        --dependencies-only) dependencies_only=1 ;;
        --sync) sync=1 ;;
        --profiles=*) profiles=${arg#*=} ;;
        --help) printf '%s\n' 'bootstrap.sh [--non-interactive] [--dependencies-only] [--profiles=shell,php,...] [--sync]'; exit 0 ;;
        *) printf 'Unknown bootstrap option: %s\n' "$arg" >&2; exit 2 ;;
    esac
done
privileged() {
    if [ "$(id -u)" = 0 ]; then "$@"
    elif [ "$mode" = non-interactive ]; then sudo -n "$@"
    else sudo "$@"; fi
}
sha256() {
    if command -v sha256sum >/dev/null 2>&1; then sha256sum < "$1" | cut -d ' ' -f 1
    else shasum -a 256 < "$1" | cut -d ' ' -f 1; fi
}
download() {
    curl -fsSL --proto '=https' --tlsv1.2 --connect-timeout 15 --max-time 300 "$1" -o "$2"
    [ "$(sha256 "$2")" = "$3" ] || { printf '%s\n' 'Bootstrap checksum mismatch.' >&2; exit 1; }
}
task_tmp=$(mktemp -d)
trap 'rm -rf "$task_tmp"' EXIT HUP INT TERM
case $(uname -s) in
    Darwin)
        platform=darwin
        for prefix in /opt/homebrew /usr/local; do
            [ ! -x "$prefix/bin/brew" ] || PATH=$prefix/bin:$PATH
        done
        export PATH
        if ! command -v brew >/dev/null 2>&1; then
            xcode-select -p >/dev/null 2>&1 || { printf '%s\n' 'Install Apple Command Line Tools with xcode-select --install, then rerun bootstrap.' >&2; exit 1; }
            download https://raw.githubusercontent.com/Homebrew/install/7a3f48c7e498d7df3237fd41c30f4d492857edf4/install.sh "$task_tmp/homebrew.sh" 5f333bbe53bc490e51e7ccb1df8779b3dd6ee73a1a7379efda216edb08ccb148
            if [ "$mode" = non-interactive ]; then NONINTERACTIVE=1 /bin/bash "$task_tmp/homebrew.sh"
            else /bin/bash "$task_tmp/homebrew.sh"; fi
            for prefix in /opt/homebrew /usr/local; do [ ! -x "$prefix/bin/brew" ] || PATH=$prefix/bin:$PATH; done
            export PATH
        fi
        for prerequisite in git curl jq; do command -v "$prerequisite" >/dev/null 2>&1 || brew install "$prerequisite"; done ;;
    Linux)
        platform=linux
        if ! command -v git >/dev/null 2>&1 || ! command -v curl >/dev/null 2>&1 || ! command -v jq >/dev/null 2>&1 || ! command -v unzip >/dev/null 2>&1; then
            if command -v apt-get >/dev/null 2>&1; then
                privileged env DEBIAN_FRONTEND=noninteractive apt-get update
                privileged env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends git curl jq ca-certificates unzip
            elif command -v dnf >/dev/null 2>&1; then privileged dnf install -y git curl jq ca-certificates unzip
            else printf '%s\n' 'Supported Linux managers: apt and dnf.' >&2; exit 1; fi
        fi ;;
    *) printf '%s\n' 'Supported systems: macOS and Linux.' >&2; exit 1 ;;
esac
case $(uname -m) in arm64|aarch64) arch=arm64 ;; x86_64|amd64) arch=amd64 ;; *) printf '%s\n' 'Supported architectures: arm64 and x86_64.' >&2; exit 1 ;; esac
: "${XDG_DATA_HOME:=$HOME/.local/share}"
safe_directory() {
    [ ! -L "$1" ] || { printf '%s\n' 'Bootstrap refuses symlinked installation directories.' >&2; exit 1; }
    ancestor=$1
    while [ ! -d "$ancestor" ]; do
        [ ! -L "$ancestor" ] || { printf '%s\n' 'Bootstrap refuses broken directory symlinks.' >&2; exit 1; }
        ancestor=$(dirname "$ancestor")
    done
    physical=$(CDPATH='' cd "$ancestor" && pwd -P)
    physical_home=$(CDPATH='' cd "$HOME" && pwd -P)
    case "$physical/" in "$physical_home/"*) ;; *) printf '%s\n' 'Bootstrap directory escapes HOME.' >&2; exit 1 ;; esac
}
safe_directory "$HOME/.local/bin"
mkdir -p "$HOME/.local/bin"
PATH=$HOME/.local/bin:$PATH
export PATH
if ! command -v chezmoi >/dev/null 2>&1; then
    case $platform-$arch in
        darwin-amd64) checksum=0ec1869c60752644863bc4690878a290455f0d35c6e9b200ca4a822b35d2be54 ;;
        darwin-arm64) checksum=19a8d9778d90476cc2f0463be69e9d82e2b91ba7b2361dbfc5348f243b1ba731 ;;
        linux-amd64) checksum=a3f958acb7d0e5d53fa43c2eec9bc8ae3b4fba8bcbfdce29a8881ca3ffc20a53 ;;
        linux-arm64) checksum=e60275b27f505ae2086bfb87b144eacf7377a89803120f6bd933d1852a93b0c6 ;;
    esac
    download "https://github.com/twpayne/chezmoi/releases/download/v2.73.1/chezmoi_2.73.1_${platform}_${arch}.tar.gz" "$task_tmp/chezmoi.tgz" "$checksum"
    tar -xzf "$task_tmp/chezmoi.tgz" -C "$task_tmp" chezmoi
    [ ! -L "$HOME/.local/bin/chezmoi" ] || { printf '%s\n' 'Refusing to overwrite chezmoi symlink.' >&2; exit 1; }
    cp "$task_tmp/chezmoi" "$HOME/.local/bin/chezmoi"
    chmod 755 "$HOME/.local/bin/chezmoi"
fi
[ "$dependencies_only" = 0 ] || exit 0
source_dir=${DOTFILES_SOURCE:-$XDG_DATA_HOME/chezmoi}
if [ ! -d "$source_dir/.git" ]; then
    [ ! -e "$source_dir" ] || { printf '%s\n' 'Source path already exists and is not a checkout.' >&2; exit 1; }
    git clone --branch master https://github.com/phcorp/dotfiles.git "$source_dir"
fi
if [ "$mode" = interactive ]; then
    DOTFILES_SOURCE=$source_dir "$source_dir/bin/dotfiles" wizard
elif [ "$sync" = 1 ]; then
    DOTFILES_SOURCE=$source_dir "$source_dir/bin/dotfiles" install --non-interactive --profiles "$profiles" --sync
else
    DOTFILES_SOURCE=$source_dir "$source_dir/bin/dotfiles" install --non-interactive --profiles "$profiles"
fi
