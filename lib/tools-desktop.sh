# Official desktop packages and Mac App Store lifecycle. Definition-only library.
# shellcheck disable=SC2030,SC2031
# Public API: desktop_supported ID, desktop_exists ID, desktop_change ID ACTION.
# Called from tools.sh, which owns operation locking and packages ownership ledger.
# shellcheck disable=SC1091
# shellcheck source=lib/tools-codexbar.sh
if [ -f "${DOTFILES_SOURCE:-}/lib/tools-codexbar.sh" ]; then . "$DOTFILES_SOURCE/lib/tools-codexbar.sh"; fi
_desktop_field() { printf '%s\n' "$1" | cut -f "$2"; }
_desktop_arch() {
    case $(uname -m) in x86_64|amd64) _desktop_arch_name=amd64 ;; aarch64|arm64) _desktop_arch_name=arm64 ;; *) return 1 ;; esac
}
_desktop_record() {
    _desktop_arch || return
    _desktop_record_value=$(awk -F '\t' -v id="$1" -v kind="$2" -v arch="$_desktop_arch_name" 'NR>1 && $1==id && $2==kind && $3==arch {print; found=1; exit} END {exit !found}' "$DOTFILES_SOURCE/lib/tools-desktop.tsv")
}
_desktop_linux_manager() {
    if command -v apt-get >/dev/null 2>&1; then _desktop_native=deb
    elif command -v dnf >/dev/null 2>&1; then _desktop_native=rpm
    else return 1; fi
}
_desktop_distro_supported() {
    [ -f /etc/os-release ] || return 1
    _desktop_distro=$(awk -F= '$1=="ID" {gsub(/"/, "", $2); print $2}' /etc/os-release)
    _desktop_version=$(awk -F= '$1=="VERSION_ID" {gsub(/"/, "", $2); print $2}' /etc/os-release)
    _desktop_major=${_desktop_version%%.*}
    case $_desktop_major in ''|*[!0-9]*) return 1 ;; esac
    case $1:$_desktop_distro in
        claude-desktop:ubuntu) [ "$_desktop_major" -ge 22 ] ;;
        claude-desktop:debian) [ "$_desktop_major" -ge 12 ] ;;
        chatgpt:ubuntu) [ "$_desktop_major" -ge 24 ] ;;
        chatgpt:debian) [ "$_desktop_major" -ge 13 ] ;;
        chatgpt:fedora) [ "$_desktop_major" -ge 43 ] ;;
        hoppscotch:ubuntu|hoppscotch:debian|hoppscotch:fedora) return 0 ;;
        *) return 1 ;;
    esac
}
desktop_supported() (
    case $1 in
        mutekey) case $(uname -s) in Darwin) return 0 ;; Linux) _desktop_linux_manager ;; *) return 1 ;; esac ;;
        codexbar) command -v codexbar_supported >/dev/null 2>&1 && codexbar_supported "$1" ;;
        chatgpt|claude-desktop|hoppscotch)
            [ "$(uname -s)" = Linux ] && _desktop_distro_supported "$1" && _desktop_linux_manager || return 1
            if [ "$1" = hoppscotch ] && [ "$_desktop_native" = rpm ]; then _desktop_native=appimage; fi
            _desktop_record "$1" "$_desktop_native" ;;
        *) return 1 ;;
    esac
)
desktop_exists() (
    case $1 in
        mutekey)
            if [ "$(uname -s)" = Linux ]; then
                [ -x "${DOTFILES_BIN:-$HOME/.local/bin}/mutekey" ]; return
            fi
            [ -d /Applications/MuteKey.app ] || [ -d "$HOME/Applications/MuteKey.app" ] && return 0
            command -v mas >/dev/null 2>&1 || return 1
            mas list 2>/dev/null | awk '$1=="1509590766" {found=1} END {exit !found}' ;;
        codexbar) command -v codexbar_exists >/dev/null 2>&1 && codexbar_exists "$1" ;;
        chatgpt|claude-desktop|hoppscotch)
            _desktop_linux_manager || return
            if [ "$1" = hoppscotch ] && [ "$_desktop_native" = rpm ]; then
                [ -f "$DOTFILES_STATE/desktop/hoppscotch.AppImage" ] && [ -x "${DOTFILES_BIN:-$HOME/.local/bin}/hoppscotch" ]; return
            fi
            if [ "$_desktop_native" = deb ]; then [ "$(dpkg-query -W -f='${Status}' "$1" 2>/dev/null)" = 'install ok installed' ]
            else rpm -q "$1" >/dev/null 2>&1; fi ;;
        *) return 1 ;;
    esac
)
_desktop_owned() {
    awk -F '\t' -v id="$1" '$1==id && $2=="desktop" && $4=="created-by-dotfiles" {found=1} END {exit !found}' "$DOTFILES_STATE/packages" 2>/dev/null
}
_desktop_download() {
    curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 --connect-timeout 15 --max-time 900 "$1" -o "$2"
}
_desktop_verify_repository() {
    _desktop_repo=$(_desktop_field "$_desktop_record_value" 9)
    [ "$_desktop_repo" != - ] || return 0
    _desktop_key=$DOTFILES_SOURCE/$(_desktop_field "$_desktop_record_value" 11)
    _desktop_fingerprint=$(_desktop_field "$_desktop_record_value" 12)
    command -v gpg >/dev/null 2>&1 || {
        if [ "$_desktop_native" = deb ]; then _tools_apt_guard install -y --no-install-recommends gnupg
        else _tools_privileged dnf install -y gnupg2; fi
    } || return
    mkdir "$_desktop_work/gnupg" || return
    chmod 700 "$_desktop_work/gnupg" || return
    _desktop_actual=$(gpg --no-options --homedir "$_desktop_work/gnupg" --batch --with-colons --show-keys "$_desktop_key" 2>/dev/null | awk -F: '$1=="fpr" {print $10; exit}')
    [ "$_desktop_actual" = "$_desktop_fingerprint" ] || { printf '%s\n' 'Desktop repository key fingerprint mismatch.' >&2; return 1; }
    gpg --no-options --homedir "$_desktop_work/gnupg" --batch --yes --dearmor --output "$_desktop_work/vendor.gpg" "$_desktop_key" >/dev/null 2>&1 || return
    _desktop_download "$_desktop_repo" "$_desktop_work/repository" || return
    _desktop_signature=$(_desktop_field "$_desktop_record_value" 10)
    if [ "$_desktop_signature" = - ]; then
        gpgv --homedir "$_desktop_work/gnupg" --keyring "$_desktop_work/vendor.gpg" "$_desktop_work/repository" >/dev/null 2>&1
    else
        _desktop_download "$_desktop_signature" "$_desktop_work/repository.asc" || return
        gpgv --homedir "$_desktop_work/gnupg" --keyring "$_desktop_work/vendor.gpg" "$_desktop_work/repository.asc" "$_desktop_work/repository" >/dev/null 2>&1
    fi || { printf '%s\n' 'Desktop repository signature verification failed.' >&2; return 1; }
}
_desktop_mas() {
    case $1 in
        install)
            desktop_exists mutekey && return 0
            if [ "${DOTFILES_MODE:-interactive}" = non-interactive ]; then
                printf '%s\n' 'MuteKey requires App Store authentication. Install it interactively after signing in, then rerun dotfiles.' >&2; return 1
            fi ;;
        upgrade)
            if [ "${DOTFILES_MODE:-interactive}" = non-interactive ]; then
                printf '%s\n' 'App Store updates require interactive authentication.' >&2; return 1
            fi ;;
    esac
    if ! command -v mas >/dev/null 2>&1; then
        command -v brew >/dev/null 2>&1 || { printf '%s\n' 'Homebrew is required to install mas.' >&2; return 1; }
        brew install mas || return
    fi
    case $1 in
        install) printf '%s\n' 'MuteKey is free. Sign in to the App Store if Apple requests authentication.'; _tools_privileged mas get 1509590766 ;;
        upgrade) _tools_privileged mas update 1509590766 ;;
        uninstall) _tools_privileged mas uninstall 1509590766 ;;
    esac
}
desktop_change() (
    umask 077
    _desktop_id=$1; _desktop_action=$2
    case $_desktop_action in install|upgrade|uninstall) ;; *) return 2 ;; esac
    _tools_paths_safe || return
    _desktop_private_safe || return
    if [ "$_desktop_action" != install ] && ! _desktop_owned "$_desktop_id"; then
        if [ "$_desktop_action" = upgrade ] && desktop_exists "$_desktop_id"; then
            case $_desktop_id in chatgpt|claude-desktop|mutekey) ;; hoppscotch) _desktop_linux_manager && [ "$_desktop_native" = deb ] || return 1 ;; *) return 1 ;; esac
        else printf '%s\n' 'Refusing to change an unowned desktop application.' >&2; return 1; fi
    fi
    case $_desktop_id in
        mutekey)
            case $(uname -s) in Darwin) _desktop_mas "$_desktop_action" ;; Linux) _desktop_mic_change "$_desktop_action" ;; *) return 1 ;; esac
            return ;;
        codexbar) codexbar_change "$_desktop_id" "$_desktop_action"; return ;;
    esac
    if [ "$_desktop_action" = install ] && desktop_exists "$_desktop_id"; then return 0; fi
    desktop_supported "$_desktop_id" || { printf '%s\n' 'This desktop application does not support this OS, distribution version, or architecture.' >&2; return 1; }
    _desktop_linux_manager || return
    if [ "$_desktop_id" = hoppscotch ] && [ "$_desktop_native" = rpm ]; then _desktop_native=appimage; fi
    if [ "$_desktop_action" = uninstall ]; then
        case $_desktop_native in
            deb) _tools_manager_name=apt; _tools_package=$_desktop_id; _tools_removal_safe && _desktop_remove_owned "$_desktop_id" && _tools_privileged env DEBIAN_FRONTEND=noninteractive apt-get remove -y "$_desktop_id" ;;
            rpm) _tools_manager_name=dnf; _tools_package=$_desktop_id; _tools_removal_safe && _tools_privileged dnf remove -y "$_desktop_id" ;;
            appimage) _desktop_appimage_remove ;;
        esac
        return
    fi
    mkdir -p "$DOTFILES_STATE" || return
    _desktop_work=$(mktemp -d "$DOTFILES_STATE/desktop-download.XXXXXX") || return
    trap 'rm -rf "$_desktop_work"' EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM
    _desktop_record "$_desktop_id" "$_desktop_native" || return
    if [ "$_desktop_native" = deb ] && [ "$_desktop_action" = upgrade ]; then
        _desktop_installed=$(dpkg-query -W -f='${Version}' "$_desktop_id" 2>/dev/null) || return
        _desktop_pinned=$(_desktop_field "$_desktop_record_value" 4)
        _desktop_pinned=${_desktop_pinned#v}
        if dpkg --compare-versions "$_desktop_installed" gt "$_desktop_pinned"; then
            printf '%s\n' 'Preserving the installed version newer than the pinned desktop release.'; return 0
        fi
    fi
    if [ "$_desktop_native" = deb ]; then _tools_privileged env DEBIAN_FRONTEND=noninteractive apt-get update || return; fi
    _desktop_verify_repository || return
    _desktop_url=$(_desktop_field "$_desktop_record_value" 5)
    _desktop_expected=$(_desktop_field "$_desktop_record_value" 6)
    _desktop_package=$_desktop_work/package.$_desktop_native
    _desktop_download "$_desktop_url" "$_desktop_package" || return
    [ "$(_tools_hash "$_desktop_package")" = "$_desktop_expected" ] || { printf '%s\n' 'Desktop package checksum mismatch.' >&2; return 1; }
    case $_desktop_native in
        deb) _tools_apt_guard install -y --no-install-recommends "$_desktop_package" ;;
        rpm) if [ "$_desktop_action" = upgrade ]; then _tools_privileged dnf upgrade -y "$_desktop_package"; else _tools_privileged dnf install -y "$_desktop_package"; fi ;;
        appimage) _desktop_appimage_install ;;
    esac
)
# AppImage is retained intact. Extraction occurs only when the app is explicitly run.
_desktop_appimage_install() (
    _tools_safe_ancestor "$DOTFILES_STATE/desktop/hoppscotch.AppImage" || return
    [ ! -L "$DOTFILES_STATE/desktop" ] && [ ! -L "$DOTFILES_STATE/desktop/hoppscotch.AppImage" ] || return 1
    mkdir -p "$DOTFILES_STATE/desktop" || return
    _desktop_bin=${DOTFILES_BIN:-$HOME/.local/bin}
    mkdir -p "$_desktop_bin" || return
    _desktop_target=$DOTFILES_STATE/desktop/hoppscotch.AppImage
    _desktop_launcher=$_desktop_bin/hoppscotch
    [ ! -L "$_desktop_launcher" ] || return 1
    if [ -e "$_desktop_launcher" ]; then
        if [ ! -f "$DOTFILES_STATE/desktop/hoppscotch-launcher.sha256" ] || [ "$(_tools_hash "$_desktop_launcher")" != "$(cat "$DOTFILES_STATE/desktop/hoppscotch-launcher.sha256")" ]; then
            printf '%s\n' 'Preserving an existing Hoppscotch launcher.' >&2; return 1
        fi
    fi
    if [ -e "$_desktop_target" ]; then
        [ -f "$DOTFILES_STATE/desktop/hoppscotch-image.sha256" ] && [ "$(_tools_hash "$_desktop_target")" = "$(cat "$DOTFILES_STATE/desktop/hoppscotch-image.sha256")" ] || return 1
    fi
    _desktop_entry_path=${XDG_DATA_HOME:-$HOME/.local/share}/applications/dotfiles-hoppscotch.desktop
    _desktop_can_write_owned hoppscotch "$_desktop_entry_path" || return
    _desktop_transaction_begin "$_desktop_target" "$_desktop_launcher" "$DOTFILES_STATE/desktop/hoppscotch-image.sha256" "$DOTFILES_STATE/desktop/hoppscotch-launcher.sha256" "$_desktop_entry_path" "$DOTFILES_STATE/desktop-files.tsv" || return
    _desktop_stage=$(mktemp "$_desktop_bin/.hoppscotch.XXXXXX") || return
    _desktop_quoted=$(printf '%s' "$_desktop_target" | sed "s/'/'\\\\''/g")
    printf '%s\n' '#!/bin/sh' "exec '$_desktop_quoted' --appimage-extract-and-run "'"$@"' > "$_desktop_stage" || return
    chmod 755 "$_desktop_stage" "$_desktop_package" || return
    mv "$_desktop_package" "$_desktop_target" && mv "$_desktop_stage" "$_desktop_launcher" || return
    _tools_hash "$_desktop_target" > "$DOTFILES_STATE/desktop/hoppscotch-image.sha256"
    _tools_hash "$_desktop_launcher" > "$DOTFILES_STATE/desktop/hoppscotch-launcher.sha256"
    _desktop_make_entry hoppscotch Hoppscotch "$_desktop_launcher" Development || return
    _desktop_transaction_ok=1
)
_desktop_appimage_remove() {
    _desktop_target=$DOTFILES_STATE/desktop/hoppscotch.AppImage
    _desktop_launcher=${DOTFILES_BIN:-$HOME/.local/bin}/hoppscotch
    for _desktop_kind in image launcher; do
        case $_desktop_kind in image) _desktop_file=$_desktop_target ;; launcher) _desktop_file=$_desktop_launcher ;; esac
        [ ! -L "$_desktop_file" ] && [ -f "$_desktop_file" ] && [ -f "$DOTFILES_STATE/desktop/hoppscotch-$_desktop_kind.sha256" ] || return 1
        [ "$(_tools_hash "$_desktop_file")" = "$(cat "$DOTFILES_STATE/desktop/hoppscotch-$_desktop_kind.sha256")" ] || { printf '%s\n' 'Preserving a modified Hoppscotch installation.' >&2; return 1; }
    done
    _desktop_remove_owned hoppscotch || return
    rm -f "$_desktop_target" "$_desktop_launcher" "$DOTFILES_STATE/desktop/hoppscotch-image.sha256" "$DOTFILES_STATE/desktop/hoppscotch-launcher.sha256"
}

_desktop_private_safe() {
    _tools_safe_ancestor "$DOTFILES_STATE/desktop/marker" || return
    for _desktop_private_file in "$DOTFILES_STATE/desktop-files.tsv" "$DOTFILES_STATE/desktop/hoppscotch-image.sha256" "$DOTFILES_STATE/desktop/hoppscotch-launcher.sha256"; do
        [ ! -L "$_desktop_private_file" ] || { printf '%s\n' 'Refusing symlinked private desktop state.' >&2; return 1; }
    done
}
_desktop_write_owned() (
    _desktop_file_id=$1; _desktop_source_file=$2; _desktop_destination=$3
    _desktop_can_write_owned "$_desktop_file_id" "$_desktop_destination" || return
    mkdir -p "$(dirname "$_desktop_destination")" "$DOTFILES_STATE" || return
    _desktop_output=$(mktemp "$(dirname "$_desktop_destination")/.dotfiles-desktop.XXXXXX") || return
    trap 'rm -f "$_desktop_output"' EXIT
    cp -p "$_desktop_source_file" "$_desktop_output" && mv "$_desktop_output" "$_desktop_destination" || return
    printf '%s\t%s\t%s\n' "$_desktop_file_id" "$(_tools_hash "$_desktop_destination")" "$_desktop_destination" >> "$DOTFILES_STATE/desktop-files.tsv"
)
_desktop_remove_owned() (
    [ -f "$DOTFILES_STATE/desktop-files.tsv" ] || return 0
    _desktop_rows=$(awk -F '\t' -v id="$1" '$1==id {rows[$3]=$0} END {for (path in rows) print rows[path]}' "$DOTFILES_STATE/desktop-files.tsv")
    [ -n "$_desktop_rows" ] || return 0
    printf '%s\n' "$_desktop_rows" | while IFS="$(printf '\t')" read -r _desktop_row_id _desktop_digest _desktop_path; do
        _tools_safe_ancestor "$_desktop_path" && _desktop_owned_path "$_desktop_row_id" "$_desktop_path" || exit 1
        [ ! -L "$_desktop_path" ] && [ -f "$_desktop_path" ] && [ "$(_tools_hash "$_desktop_path")" = "$_desktop_digest" ] || { printf '%s\n' 'Preserving modified desktop files.' >&2; exit 1; }
    done || return
    printf '%s\n' "$_desktop_rows" | while IFS="$(printf '\t')" read -r _desktop_row_id _desktop_digest _desktop_path; do rm -f "$_desktop_path" || exit; done || return
    _desktop_new=$(mktemp "$DOTFILES_STATE/desktop-files.XXXXXX") || return
    awk -F '\t' -v id="$1" '$1!=id' "$DOTFILES_STATE/desktop-files.tsv" > "$_desktop_new" && mv "$_desktop_new" "$DOTFILES_STATE/desktop-files.tsv"
)
_desktop_make_entry() (
    _desktop_entry_id=$1; _desktop_name=$2; _desktop_executable=$3; _desktop_category=$4
    _desktop_data=${XDG_DATA_HOME:-$HOME/.local/share}
    _tools_safe_ancestor "$_desktop_data/applications/.dotfiles-check" || return
    _desktop_entry=$(mktemp "$DOTFILES_STATE/desktop-entry.XXXXXX") || return
    trap 'rm -f "$_desktop_entry"' EXIT
    # shellcheck disable=SC2016
    _desktop_exec_quote=$(printf '%s' "$_desktop_executable" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' -e 's/`/\\`/g' -e 's/\$/\\$/g' -e 's/%/%%/g')
    printf '[Desktop Entry]\nType=Application\nName=%s\nExec="%s"\nTerminal=false\nCategories=%s;\n' "$_desktop_name" "$_desktop_exec_quote" "$_desktop_category" > "$_desktop_entry"
    chmod 644 "$_desktop_entry"
    _desktop_write_owned "$_desktop_entry_id" "$_desktop_entry" "$_desktop_data/applications/dotfiles-$_desktop_entry_id.desktop"
)
_desktop_mic_change() (
    _desktop_linux_manager || return
    if [ "$1" = uninstall ]; then _desktop_remove_owned mutekey; return; fi
    if ! command -v pactl >/dev/null 2>&1; then
        if [ "$_desktop_native" = deb ]; then
            _tools_privileged env DEBIAN_FRONTEND=noninteractive apt-get update && _tools_apt_guard install -y --no-install-recommends pulseaudio-utils || return
        else _tools_privileged dnf install -y pulseaudio-utils || return; fi
    fi
    mkdir -p "$DOTFILES_STATE" || return
    _desktop_helper_target=${DOTFILES_BIN:-$HOME/.local/bin}/mutekey
    _desktop_entry_path=${XDG_DATA_HOME:-$HOME/.local/share}/applications/dotfiles-mutekey.desktop
    _desktop_can_write_owned mutekey "$_desktop_helper_target" && _desktop_can_write_owned mutekey "$_desktop_entry_path" || return
    _desktop_transaction_begin "$_desktop_helper_target" "$_desktop_entry_path" "$DOTFILES_STATE/desktop-files.tsv" || return
    _desktop_helper=$(mktemp "$_desktop_transaction_dir/mic-helper.XXXXXX") || return
    printf '%s\n' '#!/bin/sh' 'exec pactl set-source-mute @DEFAULT_SOURCE@ toggle "$@"' > "$_desktop_helper"
    chmod 755 "$_desktop_helper"
    _desktop_helper_target=${DOTFILES_BIN:-$HOME/.local/bin}/mutekey
    _desktop_write_owned mutekey "$_desktop_helper" "$_desktop_helper_target" || return
    _desktop_make_entry mutekey 'Toggle microphone mute' "$_desktop_helper_target" AudioVideo || return
    _desktop_transaction_ok=1
)

_desktop_owned_path() {
    _desktop_allowed_bin=${DOTFILES_BIN:-$HOME/.local/bin}
    _desktop_allowed_data=${XDG_DATA_HOME:-$HOME/.local/share}
    case $1:$2 in
        "mutekey:$_desktop_allowed_bin/mutekey"|"mutekey:$_desktop_allowed_data/applications/dotfiles-mutekey.desktop"|"hoppscotch:$_desktop_allowed_data/applications/dotfiles-hoppscotch.desktop"|"hoppscotch:$_desktop_allowed_bin/hoppscotch") return 0 ;;
        *) printf '%s\n' 'Invalid desktop ownership path.' >&2; return 1 ;;
    esac
}

_desktop_can_write_owned() (
    _desktop_check_id=$1; _desktop_check_path=$2
    _tools_safe_ancestor "$_desktop_check_path" && _desktop_owned_path "$_desktop_check_id" "$_desktop_check_path" || return
    [ ! -L "$_desktop_check_path" ] && [ ! -d "$_desktop_check_path" ] || return 1
    if [ -e "$_desktop_check_path" ]; then
        _desktop_recorded=$(awk -F '\t' -v id="$_desktop_check_id" -v path="$_desktop_check_path" '$1==id && $3==path {sha=$2} END {print sha}' "$DOTFILES_STATE/desktop-files.tsv" 2>/dev/null)
        if [ -z "$_desktop_recorded" ] || [ "$(_tools_hash "$_desktop_check_path")" != "$_desktop_recorded" ]; then
            printf '%s\n' 'Preserving an existing or modified desktop file.' >&2; return 1
        fi
    fi
)
_desktop_transaction_begin() {
    _desktop_transaction_dir=$(mktemp -d "$DOTFILES_STATE/desktop-transaction.XXXXXX") || return
    _desktop_transaction_ok=0
    printf '%s\n' "$@" > "$_desktop_transaction_dir/paths" || return
    _desktop_transaction_index=0
    while IFS= read -r _desktop_transaction_path; do
        _desktop_transaction_index=$((_desktop_transaction_index + 1))
        _tools_safe_ancestor "$_desktop_transaction_path" || return
        [ ! -L "$_desktop_transaction_path" ] && [ ! -d "$_desktop_transaction_path" ] || return 1
        if [ -f "$_desktop_transaction_path" ]; then
            cp -p "$_desktop_transaction_path" "$_desktop_transaction_dir/$_desktop_transaction_index" || return
        fi
    done < "$_desktop_transaction_dir/paths"
    trap '_desktop_transaction_finish' EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM
}
_desktop_transaction_finish() {
    _desktop_rollback_failed=0
    if [ "$_desktop_transaction_ok" != 1 ]; then
        _desktop_transaction_index=0
        while IFS= read -r _desktop_transaction_path; do
            _desktop_transaction_index=$((_desktop_transaction_index + 1))
            _tools_safe_ancestor "$_desktop_transaction_path" || { _desktop_rollback_failed=1; continue; }
            if [ -L "$_desktop_transaction_path" ] || [ -d "$_desktop_transaction_path" ]; then
                _desktop_rollback_failed=1; continue
            fi
            if [ -f "$_desktop_transaction_dir/$_desktop_transaction_index" ]; then
                cp -p "$_desktop_transaction_dir/$_desktop_transaction_index" "$_desktop_transaction_path" || { _desktop_rollback_failed=1; printf '%s\n' 'Desktop rollback needs manual recovery from private transaction backup.' >&2; }
            else rm -f "$_desktop_transaction_path" || _desktop_rollback_failed=1; fi
        done < "$_desktop_transaction_dir/paths"
    fi
    if [ "$_desktop_rollback_failed" = 0 ]; then rm -rf "$_desktop_transaction_dir"; else printf '%s\n' 'Desktop recovery snapshot retained because safe rollback could not finish.' >&2; fi
    [ -z "${_desktop_stage:-}" ] || rm -f "$_desktop_stage"
}
# Canonical invocation for the official Debian package's differently named binary.
desktop_alias() (
    [ "$1" = hoppscotch ] && [ "$(uname -s)" = Linux ] || return 0
    command -v apt-get >/dev/null 2>&1 || return 0
    [ -x /usr/bin/hoppscotch-desktop ] || return 0
    command -v hoppscotch >/dev/null 2>&1 && return 0
    _tools_paths_safe && _desktop_private_safe || return
    mkdir -p "$DOTFILES_STATE" || return
    _desktop_alias_file=$(mktemp "$DOTFILES_STATE/native-alias.XXXXXX") || return
    trap 'rm -f "$_desktop_alias_file"' EXIT
    printf '%s\n' '#!/bin/sh' 'exec /usr/bin/hoppscotch-desktop "$@"' > "$_desktop_alias_file" || return
    chmod 755 "$_desktop_alias_file" || return
    _desktop_write_owned hoppscotch "$_desktop_alias_file" "${DOTFILES_BIN:-$HOME/.local/bin}/hoppscotch"
)
