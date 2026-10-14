# Verified Linux CodexBar bundles. Application configuration is never managed here.
# shellcheck disable=SC2030,SC2031
codexbar_supported() (
    [ "$1" = codexbar ] && [ "$(uname -s)" = Linux ] || return 1
    case $(uname -m) in x86_64|amd64|aarch64|arm64) ;; *) return 1 ;; esac
)
_codexbar_paths() {
    _cb_root=${XDG_DATA_HOME:-$HOME/.local/share}/dotfiles/apps/codexbar
    _cb_bin=${DOTFILES_BIN:-$HOME/.local/bin}
    _cb_manifest=$DOTFILES_STATE/codexbar-manifest.tsv
    _cb_files=$DOTFILES_STATE/codexbar-files.tsv
    _cb_desktop_entry=${XDG_DATA_HOME:-$HOME/.local/share}/applications/codexbar.desktop
    _tools_safe_ancestor "$_cb_desktop_entry" || return
    _tools_safe_ancestor "$_cb_root/placeholder" && _tools_safe_ancestor "$_cb_bin/placeholder" || return
    for _cb_private in "$_cb_root" "$_cb_manifest" "$_cb_files"; do
        [ ! -L "$_cb_private" ] || { printf '%s\n' 'Refusing symlinked CodexBar installation state.' >&2; return 1; }
    done
}
codexbar_exists() (
    _codexbar_paths || return
    [ -d "$_cb_root" ] && [ -f "$_cb_manifest" ] && [ -f "$_cb_files" ] || return 1
    [ -x "$_cb_bin/codexbar" ] || return 1
    _cb_installed_cli=$(find "$_cb_root/cli" -type f -name CodexBarCLI -perm -111 | head -n 1)
    [ -n "$_cb_installed_cli" ]
)
_codexbar_desktop_supported() {
    _cb_glibc=$(getconf GNU_LIBC_VERSION 2>/dev/null) || return 1
    _cb_glibc=${_cb_glibc#glibc }
    _cb_major=${_cb_glibc%%.*}; _cb_minor=${_cb_glibc#*.}; _cb_minor=${_cb_minor%%.*}
    case $_cb_major:$_cb_minor in *[!0-9:]*) return 1 ;; esac
    [ "$_cb_major" -gt 2 ] || { [ "$_cb_major" -eq 2 ] && [ "$_cb_minor" -ge 39 ]; }
}
_codexbar_dependencies() {
    if command -v apt-get >/dev/null 2>&1; then
        _tools_privileged env DEBIAN_FRONTEND=noninteractive apt-get update || return
        _cb_widgets=libqt6widgets6
        if apt-cache show libqt6widgets6t64 >/dev/null 2>&1; then _cb_widgets=libqt6widgets6t64; fi
        _tools_apt_guard install -y --no-install-recommends qml6-module-qtquick qml6-module-qtquick-controls \
                qml6-module-qtquick-layouts qml6-module-qtquick-templates qml6-module-qtquick-window \
                qml6-module-qtqml-workerscript "$_cb_widgets" libqt6svg6 qt6-wayland
    elif command -v dnf >/dev/null 2>&1; then
        _tools_privileged dnf -y install qt6-qtbase qt6-qtdeclarative qt6-qtsvg qt6-qtwayland
    else return 1; fi
}
_codexbar_download() {
    _cb_row=$(awk -F '\t' -v backend="$1" -v arch="$_cb_arch" '$1=="codexbar" && $2==backend && $3==arch {print; found=1; exit} END {exit !found}' "$DOTFILES_SOURCE/lib/tools-desktop.tsv") || return
    _cb_url=$(_tools_field "$_cb_row" 5); _cb_sha=$(_tools_field "$_cb_row" 6)
    _cb_archive=$_cb_work/$1.tgz
    curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 --connect-timeout 15 --max-time 300 "$_cb_url" -o "$_cb_archive" || return
    [ "$(_tools_hash "$_cb_archive")" = "$_cb_sha" ] || { printf '%s\n' 'CodexBar checksum mismatch.' >&2; return 1; }
    tar -tzf "$_cb_archive" > "$_cb_work/entries" || return
    if ! awk '/^\// || /(^|\/)\.\.(\/|$)/ || /\t/ {bad=1} END {exit bad}' "$_cb_work/entries"; then
        printf '%s\n' 'Unsafe CodexBar archive path.' >&2; return 1
    fi
    mkdir "$_cb_work/$1" || return
    tar -xzf "$_cb_archive" -C "$_cb_work/$1" || return
}
_codexbar_inventory() (
    _cb_inventory_root=$1
    cd "$_cb_inventory_root" || return
    _cb_scan=$(mktemp "$DOTFILES_STATE/codexbar-scan.XXXXXX") || return
    trap 'rm -f "$_cb_scan"' EXIT
    find . \( -type f -o -type l \) -print | LC_ALL=C sort > "$_cb_scan" || return
    while IFS= read -r _cb_file; do
        if [ -L "$_cb_file" ]; then _cb_hash=link:$(readlink "$_cb_file")
        else _cb_hash=$(_tools_hash "$_cb_file") || return; fi
        printf '%s\t%s\n' "$_cb_hash" "$_cb_file" || return
    done < "$_cb_scan"
)
_codexbar_owned_clean() {
    _cb_inventory=$(mktemp "$DOTFILES_STATE/codexbar-check.XXXXXX") || return
    if ! _codexbar_inventory "$_cb_root" > "$_cb_inventory" || ! cmp -s "$_cb_inventory" "$_cb_manifest"; then
        rm -f "$_cb_inventory"
        printf '%s\n' 'CodexBar payload changed; preserving it for manual review.' >&2; return 1
    fi
    rm -f "$_cb_inventory" || return
    while IFS="$(printf '\t')" read -r _cb_digest _cb_path; do
        case $_cb_path in "$_cb_bin/codexbar"|"$_cb_bin/codexbar-desktop"|"$_cb_desktop_entry") ;; *) return 1 ;; esac
        _tools_safe_ancestor "$_cb_path" || return
        [ ! -L "$_cb_path" ] && [ -f "$_cb_path" ] && [ "$(_tools_hash "$_cb_path")" = "$_cb_digest" ] || {
            printf '%s\n' 'CodexBar launcher changed; preserving it for manual review.' >&2; return 1;
        }
    done < "$_cb_files"
}
_codexbar_write_launcher() {
    _cb_target=$1; _cb_executable=$2
    _tools_safe_ancestor "$_cb_target" || return
    [ ! -e "$_cb_target" ] && [ ! -L "$_cb_target" ] || { printf '%s\n' 'CodexBar launcher already exists; preserving it.' >&2; return 1; }
    _cb_quoted=$(printf '%s' "$_cb_executable" | sed "s/'/'\\\\''/g")
    printf '%s\n' '#!/bin/sh' "exec '$_cb_quoted' "'"$@"' > "$_cb_target" || return
    chmod 755 "$_cb_target" || return
    printf '%s\t%s\n' "$(_tools_hash "$_cb_target")" "$_cb_target" >> "$_cb_files" || return
}
codexbar_change() (
    [ "$1" = codexbar ] || return 2
    _cb_action=$2
    _codexbar_paths || return
    case $_cb_action in
        uninstall)
            codexbar_exists codexbar || return 1
            _codexbar_owned_clean || return
            while IFS="$(printf '\t')" read -r _cb_digest _cb_path; do rm -f "$_cb_path" || return; done < "$_cb_files"
            rm -rf "$_cb_root" || return
            rm -f "$_cb_manifest" "$_cb_files"
            return ;;
        install|upgrade) ;; *) return 2 ;;
    esac
    _cb_existing=0
    if [ -e "$_cb_root" ]; then
        codexbar_exists codexbar && _codexbar_owned_clean || return
        _cb_existing=1
        [ "$_cb_action" != install ] || return 0
    fi
    codexbar_supported codexbar || return
    case $(uname -m) in x86_64|amd64) _cb_arch=amd64 ;; aarch64|arm64) _cb_arch=arm64 ;; esac
    if [ "$_cb_existing" = 0 ]; then
        for _cb_entry in "$_cb_bin/codexbar" "$_cb_bin/codexbar-desktop" "$_cb_desktop_entry"; do
            [ ! -e "$_cb_entry" ] && [ ! -L "$_cb_entry" ] || { printf '%s\n' 'Existing CodexBar launcher preserved.' >&2; return 1; }
        done
    fi
    _cb_work=$(mktemp -d "$DOTFILES_STATE/codexbar-download.XXXXXX") || return
    _cb_started=0; _cb_committed=0
    trap 'if _codexbar_rollback; then rm -rf "$_cb_work"; else printf "%s\n" "CodexBar rollback incomplete; recovery files retained." >&2; fi' EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM
    _codexbar_download codexbar-cli || return
    _cb_cli=$(find "$_cb_work/codexbar-cli" -type f -name CodexBarCLI | head -n 1)
    [ -n "$_cb_cli" ] || return 1
    _cb_desktop=
    if _codexbar_desktop_supported; then
        _codexbar_download codexbar-desktop || return
        _cb_desktop=$(find "$_cb_work/codexbar-desktop" -type f -name codexbar-linux | head -n 1)
        [ -n "$_cb_desktop" ] || return 1
        _codexbar_dependencies || return
    else
        printf '%s\n' 'CodexBar desktop requires glibc 2.39; installing the portable CLI bundle.'
    fi
    mkdir -p "$(dirname "$_cb_root")" "$_cb_bin" || return
    if [ "$_cb_existing" = 1 ]; then
        cp -p "$_cb_files" "$_cb_work/files.before" && cp -p "$_cb_manifest" "$_cb_work/manifest.before" || return
        mkdir "$_cb_work/launchers" || return
        while IFS="$(printf '\t')" read -r _cb_digest _cb_path; do cp -p "$_cb_path" "$_cb_work/launchers/$(basename "$_cb_path")" || return; done < "$_cb_files"
        mv "$_cb_root" "$_cb_work/previous" || return
        _cb_started=1
        while IFS="$(printf '\t')" read -r _cb_digest _cb_path; do rm -f "$_cb_path" || return; done < "$_cb_files"
    else _cb_started=1; fi
    mkdir "$_cb_root" || return
    mv "$_cb_work/codexbar-cli" "$_cb_root/cli" || return
    _cb_cli=$_cb_root/cli/${_cb_cli#"$_cb_work/codexbar-cli/"}
    if [ -n "$_cb_desktop" ]; then
        mv "$_cb_work/codexbar-desktop" "$_cb_root/desktop" || return
        _cb_desktop=$_cb_root/desktop/${_cb_desktop#"$_cb_work/codexbar-desktop/"}
    fi
    : > "$_cb_files" || return
    _codexbar_write_launcher "$_cb_bin/codexbar" "$_cb_cli" || return
    if [ -n "$_cb_desktop" ]; then
        _codexbar_write_launcher "$_cb_bin/codexbar-desktop" "$_cb_desktop" || return
        mkdir -p "$(dirname "$_cb_desktop_entry")" || return
        # shellcheck disable=SC2016
        _cb_desktop_exec=$(printf '%s' "$_cb_bin/codexbar-desktop" | sed 's/\\/\\\\/g;s/"/\\"/g;s/`/\\`/g;s/\$/\\$/g;s/%/%%/g')
        printf '%s\n' '[Desktop Entry]' 'Type=Application' 'Name=CodexBar' "Exec=\"$_cb_desktop_exec\"" 'Terminal=false' 'Categories=Utility;Development;' > "$_cb_desktop_entry" || return
        chmod 644 "$_cb_desktop_entry" || return
        printf '%s\t%s\n' "$(_tools_hash "$_cb_desktop_entry")" "$_cb_desktop_entry" >> "$_cb_files" || return
    fi
    _codexbar_inventory "$_cb_root" > "$_cb_manifest" || return
    _cb_committed=1
    # No upstream install.py, private config changes, application launch, or autostart.
)

_codexbar_rollback() {
    [ "$_cb_started" = 1 ] && [ "$_cb_committed" = 0 ] || return 0
    rm -rf "$_cb_root" || return
    rm -f "$_cb_bin/codexbar" "$_cb_bin/codexbar-desktop" "$_cb_desktop_entry" || return
    if [ -d "$_cb_work/previous" ]; then
        mv "$_cb_work/previous" "$_cb_root" || return
        while IFS="$(printf '\t')" read -r _cb_restore_digest _cb_restore_path; do
            cp -p "$_cb_work/launchers/$(basename "$_cb_restore_path")" "$_cb_restore_path" || return
        done < "$_cb_work/files.before"
        cp -p "$_cb_work/files.before" "$_cb_files" && cp -p "$_cb_work/manifest.before" "$_cb_manifest" || return
    else rm -f "$_cb_files" "$_cb_manifest" || return; fi
}
