# Cataloged dependency management. Source this file; functions return statuses.
# shellcheck disable=SC2030,SC2031

_tools_row() {
    case $1 in ''|*[!a-z0-9-]*) return 2 ;; esac
    awk -F '\t' -v id="$1" 'NR > 1 && $1 == id {print; found=1; exit} END {if (!found) exit 2}' "$DOTFILES_SOURCE/catalog.tsv"
}
_tools_field() { printf '%s\n' "$1" | cut -f "$2"; }
tools_list() { cat "$DOTFILES_SOURCE/catalog.tsv"; }
_tools_available() {
    _tools_cmd=$(_tools_field "$1" 2)
    command -v "$_tools_cmd" >/dev/null 2>&1
}
_tools_alias() {
    _tools_paths_safe || return
    _tools_alias_command=$1
    _tools_desktop_alias=0
    case $1 in
        fd) _tools_alt=fdfind ;; bat) _tools_alt=batcat ;;
        psql|mysql)
            command -v brew >/dev/null 2>&1 || return 0
            case $1 in psql) _tools_formula=libpq ;; mysql) _tools_formula=mysql-client ;; esac
            _tools_prefix=$(brew --prefix "$_tools_formula" 2>/dev/null) || return 0
            _tools_target=$_tools_prefix/bin/$1
            [ -x "$_tools_target" ] || return 0 ;;
        code|firefox|chrome|jetbrains-toolbox|pgadmin|orbstack|utm)
            [ "$(uname -s)" = Darwin ] || return 0
            _tools_desktop_alias=1
            case $1 in
                code) _tools_app='Visual Studio Code.app'; _tools_app_binary=Contents/Resources/app/bin/code ;;
                firefox) _tools_app=Firefox.app; _tools_app_binary=Contents/MacOS/firefox ;;
                chrome) _tools_app='Google Chrome.app'; _tools_app_binary='Contents/MacOS/Google Chrome'; _tools_alias_command=google-chrome ;;
                jetbrains-toolbox) _tools_app='JetBrains Toolbox.app'; _tools_app_binary=Contents/MacOS/jetbrains-toolbox ;;
                pgadmin) _tools_app='pgAdmin 4.app'; _tools_app_binary='Contents/MacOS/pgAdmin 4'; _tools_alias_command=pgadmin4 ;;
                orbstack) _tools_app=OrbStack.app; _tools_app_binary=Contents/MacOS/bin/orb; _tools_alias_command=orb ;;
                utm) _tools_app=UTM.app; _tools_app_binary=Contents/MacOS/utmctl; _tools_alias_command=utmctl ;;
            esac
            _tools_target=/Applications/$_tools_app/$_tools_app_binary
            if [ ! -x "$_tools_target" ]; then _tools_target=$HOME/Applications/$_tools_app/$_tools_app_binary; fi
            [ -x "$_tools_target" ] || return 0 ;;
        *) return 0 ;;
    esac
    case $1 in fd|bat) _tools_target=$(command -v "$_tools_alt") || return 0 ;; esac
    _tools_bin=${DOTFILES_BIN:-$HOME/.local/bin}
    if ! command -v "$_tools_alias_command" >/dev/null 2>&1 && [ ! -e "$_tools_bin/$_tools_alias_command" ] && [ ! -L "$_tools_bin/$_tools_alias_command" ]; then
        mkdir -p "$_tools_bin" || return
        if [ "$_tools_desktop_alias" = 1 ]; then
            _tools_app_shim "$1" || return
        else
            ln -s "$_tools_target" "$_tools_bin/$_tools_alias_command"
        fi
    fi
}

_tools_manager() {
    case $(uname -s) in
        Darwin) _tools_manager_name=brew; _tools_column=3 ;;
        Linux)
            if command -v apt-get >/dev/null 2>&1; then _tools_manager_name=apt; _tools_column=4
            elif command -v dnf >/dev/null 2>&1; then _tools_manager_name=dnf; _tools_column=5
            else printf '%s\n' 'Unsupported Linux package manager.' >&2; return 1; fi ;;
        *) printf '%s\n' 'Unsupported operating system.' >&2; return 1 ;;
    esac
    _tools_package=$(_tools_field "$_tools_record" "$_tools_column")
    if [ "$_tools_manager_name" = apt ] && [ "$_tools_package" != - ] && command -v apt-cache >/dev/null 2>&1 && ! apt-cache show "$_tools_package" >/dev/null 2>&1; then
        if _tools_upstream_record; then _tools_manager_name=upstream; _tools_package=$_tools_id; return 0; fi
    fi
    if [ "$_tools_package" = - ]; then
        if _tools_upstream_record; then _tools_manager_name=upstream; _tools_package=$_tools_id; return 0; fi
        printf 'No supported native package for %s on this system. Install it manually, then rerun doctor.\n' "$_tools_id" >&2
        return 1
    fi
    if [ "$_tools_manager_name" = brew ] && ! command -v brew >/dev/null 2>&1; then
        printf '%s\n' 'Homebrew is required; run the bootstrap wizard first.' >&2; return 1
    fi
}
_tools_privileged() {
    if [ "$(id -u)" = 0 ]; then "$@"
    elif ! command -v sudo >/dev/null 2>&1; then printf '%s\n' 'Installation requires root or sudo.' >&2; return 1
    elif [ "${DOTFILES_MODE:-interactive}" = non-interactive ]; then sudo -n "$@"
    else sudo "$@"; fi
}
_tools_package_exists() {
    case $_tools_manager_name in
        upstream) [ -f "${DOTFILES_BIN:-$HOME/.local/bin}/$_tools_id" ] ;;
        brew) case $_tools_package in cask:*) brew list --cask "${_tools_package#cask:}" >/dev/null 2>&1 ;; *) brew list --formula "$_tools_package" >/dev/null 2>&1 ;; esac ;;
        apt) [ "$(dpkg-query -W -f='${Status}' "$_tools_package" 2>/dev/null)" = 'install ok installed' ] ;;
        dnf) rpm -q "$_tools_package" >/dev/null 2>&1 ;;
    esac
}
_tools_native() {
    _tools_operation=$1
    case $_tools_manager_name in
        upstream) _tools_upstream "$_tools_operation" ;;
        brew)
            case $_tools_package in cask:*) brew "$_tools_operation" --cask "${_tools_package#cask:}" ;; *) brew "$_tools_operation" --formula "$_tools_package" ;; esac ;;
        apt)
            case $_tools_operation in
                install) _tools_privileged env DEBIAN_FRONTEND=noninteractive apt-get update && _tools_apt_guard install -y --no-install-recommends "$_tools_package" ;;
                upgrade) _tools_apt_guard install -y --only-upgrade "$_tools_package" ;;
                uninstall) _tools_privileged env DEBIAN_FRONTEND=noninteractive apt-get remove -y "$_tools_package" ;;
            esac ;;
        dnf)
            case $_tools_operation in upgrade) _tools_operation=upgrade ;; uninstall) _tools_operation=remove ;; esac
            _tools_privileged dnf -y "$_tools_operation" "$_tools_package" ;;
    esac
}
# Subshell confines variables and traps to the individual operation.
_tools_change() (
    umask 077
    _tools_id=$1; _tools_action=$2
    _tools_paths_safe || return
    _tools_record=$(_tools_row "$_tools_id") || { printf 'Unknown tool: %s\n' "$_tools_id" >&2; return 2; }
    if [ "$_tools_action" = install ] && [ "${DOTFILES_DRY_RUN:-0}" != 1 ]; then _tools_alias "$_tools_id"; fi
    if [ "$_tools_action" = install ] && _tools_available "$_tools_record"; then return 0; fi
    _tools_manager || return
    if [ "$_tools_action" != install ]; then
        _tools_owned=$(awk -F '\t' -v id="$_tools_id" '$1==id && $4=="created-by-dotfiles" {print; exit}' "$DOTFILES_STATE/packages" 2>/dev/null)
        if [ -z "$_tools_owned" ]; then
            printf 'Refusing %s: %s was not installed by dotfiles.\n' "$_tools_action" "$_tools_id" >&2; return 1
        fi
        _tools_manager_name=$(_tools_field "$_tools_owned" 2)
        _tools_package=$(_tools_field "$_tools_owned" 3)
    fi
    if [ "${DOTFILES_DRY_RUN:-0}" = 1 ]; then printf '%s %s (%s)\n' "$_tools_action" "$_tools_id" "$_tools_manager_name"; return 0; fi
    mkdir -p "$DOTFILES_STATE" || return
    _tools_lock=$DOTFILES_STATE/tools.lock
    if ! mkdir "$_tools_lock" 2>/dev/null; then printf '%s\n' 'Another tool operation is running; retry later.' >&2; return 1; fi
    trap 'rmdir "$_tools_lock" 2>/dev/null || :' EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM
    _tools_ownership=$DOTFILES_STATE/packages
    touch "$_tools_ownership" || return
    case $_tools_action in
        install)
            if _tools_available "$_tools_record"; then return 0; fi
            _tools_existing=0
            _tools_package_exists && _tools_existing=1
            _tools_native install || return
            if [ "$_tools_existing" = 0 ]; then
                printf '%s\t%s\t%s\tcreated-by-dotfiles\n' "$_tools_id" "$_tools_manager_name" "$_tools_package" >> "$_tools_ownership" || return
            fi
            _tools_alias "$_tools_id"
            if ! _tools_available "$_tools_record"; then
                printf 'Installed %s, but its command is not on PATH; run doctor.\n' "$_tools_id" >&2; return 1
            fi ;;
        upgrade) _tools_native upgrade ;;
        uninstall)
            case $_tools_id in node|python|ruby|go|rust|bun|deno) printf '%s\n' 'Runtime removal is deliberately unsupported; use its original manager.' >&2; return 1 ;; esac
            if ! awk -F '\t' -v id="$_tools_id" -v manager="$_tools_manager_name" -v package="$_tools_package" '$1==id && $2==manager && $3==package && $4=="created-by-dotfiles" {found=1} END {exit !found}' "$_tools_ownership"; then
                printf 'Refusing removal: %s was not installed by dotfiles.\n' "$_tools_id" >&2; return 1
            fi
            _tools_removal_safe || return
            _tools_native uninstall || return
            _tools_ledger_new=$(mktemp "$DOTFILES_STATE/packages.XXXXXX") || return
            awk -F '\t' -v id="$_tools_id" '$1 != id' "$_tools_ownership" > "$_tools_ledger_new" && mv "$_tools_ledger_new" "$_tools_ownership"
            case $_tools_id in fd|bat|psql|mysql)
                _tools_bin=${DOTFILES_BIN:-$HOME/.local/bin}
                if [ -L "$_tools_bin/$_tools_id" ]; then
                    _tools_link=$(readlink "$_tools_bin/$_tools_id")
                    case $_tools_link in */fdfind|*/batcat|*/libpq/bin/psql|*/mysql-client/bin/mysql) rm "$_tools_bin/$_tools_id" ;; esac
                fi ;;
                code|firefox|chrome|jetbrains-toolbox|pgadmin|orbstack|utm)
                    _tools_remove_app_shim "$_tools_id" ;;
            esac ;;
    esac
)
tools_install() { _tools_change "$1" install; }
tools_update() { _tools_change "$1" upgrade; }
tools_remove() { _tools_change "$1" uninstall; }
tools_ensure() (
    _tools_paths_safe || return
    _tools_record=$(_tools_row "$1") || return 2
    if [ "${DOTFILES_DRY_RUN:-0}" != 1 ]; then _tools_alias "$1" || return; fi
    _tools_available "$_tools_record" && return 0
    [ -f "$DOTFILES_CONFIG/tools" ] && awk -v id="$1" '$0==id {found=1} END {exit !found}' "$DOTFILES_CONFIG/tools" || return 127
    if [ "${DOTFILES_MODE:-interactive}" = interactive ]; then
        if ! { printf 'Install selected tool %s? [y/N] ' "$1" > /dev/tty; } 2>/dev/null; then return 1; fi
        IFS= read -r _tools_answer < /dev/tty || return 1
        case $_tools_answer in y|Y|yes|YES) ;; *) return 1 ;; esac
    fi
    tools_install "$1"
)

_tools_upstream_record() {
    case $(uname -s) in Darwin) _tools_os=darwin ;; Linux) _tools_os=linux ;; *) return 1 ;; esac
    case $(uname -m) in x86_64|amd64) _tools_arch=amd64 ;; arm64|aarch64) _tools_arch=arm64 ;; *) return 1 ;; esac
    _tools_release=$(awk -F '\t' -v id="$_tools_id" -v os="$_tools_os" -v arch="$_tools_arch" 'NR>1 && $1==id && $2==os && $3==arch {print; found=1; exit} END {exit !found}' "$DOTFILES_SOURCE/lib/tools-upstream.tsv")
}
_tools_upstream() {
    _tools_bin=${DOTFILES_BIN:-$HOME/.local/bin}
    if [ "$1" = uninstall ]; then rm -f "$_tools_bin/$_tools_id"; return; fi
    _tools_upstream_record || return
    _tools_url=$(_tools_field "$_tools_release" 4)
    _tools_sha=$(_tools_field "$_tools_release" 5)
    _tools_format=$(_tools_field "$_tools_release" 7)
    command -v curl >/dev/null 2>&1 || { printf '%s\n' 'curl is required for verified downloads.' >&2; return 1; }
    _tools_work=$(mktemp -d "$DOTFILES_STATE/download.XXXXXX") || return
    trap '[ -z "${_tools_stage:-}" ] || rm -f "$_tools_stage"; rm -rf "$_tools_work"; rmdir "$_tools_lock" 2>/dev/null || :' EXIT
    curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 --connect-timeout 15 --max-time 300 "$_tools_url" -o "$_tools_work/archive" || return
    if command -v sha256sum >/dev/null 2>&1; then _tools_actual=$(sha256sum "$_tools_work/archive" | cut -d ' ' -f 1)
    elif command -v shasum >/dev/null 2>&1; then _tools_actual=$(shasum -a 256 "$_tools_work/archive" | cut -d ' ' -f 1)
    else printf '%s\n' 'A SHA-256 checker is required.' >&2; return 1; fi
    [ "$_tools_actual" = "$_tools_sha" ] || { printf '%s\n' 'Download checksum mismatch; installation stopped.' >&2; return 1; }
    mkdir "$_tools_work/extracted" || return
    case $_tools_format in
        tar) tar -xzf "$_tools_work/archive" -C "$_tools_work/extracted" || return ;;
        zip) command -v unzip >/dev/null 2>&1 || { printf '%s\n' 'unzip is required.' >&2; return 1; }; unzip -q "$_tools_work/archive" -d "$_tools_work/extracted" || return ;;
        raw) cp "$_tools_work/archive" "$_tools_work/extracted/$_tools_id" || return ;;
        *) return 2 ;;
    esac
    _tools_executable=$(find "$_tools_work/extracted" -type f -name "$_tools_id" | head -n 1)
    [ -n "$_tools_executable" ] || return 1
    mkdir -p "$_tools_bin" || return
    # Never follow a preexisting destination symlink.
    [ ! -L "$_tools_bin/$_tools_id" ] || { printf '%s\n' 'Refusing to replace a symlink.' >&2; return 1; }
    [ ! -d "$_tools_bin/$_tools_id" ] || return 1
    _tools_stage=$(mktemp "$_tools_bin/.$_tools_id.XXXXXX") || return
    cp "$_tools_executable" "$_tools_stage" && chmod 755 "$_tools_stage" || return
    [ ! -L "$_tools_bin/$_tools_id" ] && [ ! -d "$_tools_bin/$_tools_id" ] || return 1
    mv "$_tools_stage" "$_tools_bin/$_tools_id"
}
# Wizard capability filter; no filesystem or package-manager mutation.
tools_supported() (
    _tools_id=$1
    _tools_record=$(_tools_row "$_tools_id") || return
    _tools_available "$_tools_record" && return 0
    _tools_manager >/dev/null 2>&1
)

_tools_apt_guard() {
    # The privileged subprocess owns restoration even when apt fails or is interrupted.
    # shellcheck disable=SC2016
    _tools_privileged sh -c '
        set -eu
        umask 077
        work=$(mktemp -d /tmp/dotfiles-policy.XXXXXX)
        original=0
        policy=/usr/sbin/policy-rc.d
        restore() {
            if [ "$original" = 1 ]; then mv "$work/original" "$policy"; else rm -f "$policy"; fi
            rmdir "$work"
        }
        if [ -e "$policy" ] || [ -L "$policy" ]; then mv "$policy" "$work/original"; original=1; fi
        trap restore EXIT
        trap "exit 130" INT
        trap "exit 143" TERM
        printf "#!/bin/sh\nexit 101\n" > "$policy"
        chmod 755 "$policy"
        DEBIAN_FRONTEND=noninteractive apt-get "$@"
    ' dotfiles-apt "$@"
}
_tools_removal_safe() {
    case $_tools_manager_name in
        upstream) return 0 ;;
        brew)
            case $_tools_package in cask:*) return 0 ;; esac
            _tools_dependents=$(brew uses --installed "$_tools_package") || return
            ;;
        apt)
            _tools_dependents=$(apt-cache rdepends --installed "$_tools_package") || return
            _tools_dependents=$(printf '%s\n' "$_tools_dependents" | awk 'NR>2 && $0 ~ /^  / {print}') ;;
        dnf)
            # Query every provided capability, including shared-library sonames.
            _tools_provides=$(rpm -q --provides "$_tools_package") || return
            _tools_dependents=$(printf '%s\n' "$_tools_provides" | while IFS= read -r _tools_provide; do
                _tools_capability=${_tools_provide%% *}
                _tools_required=$(rpm -q --qf '%{NAME}\n' --whatrequires "$_tools_capability" 2>/dev/null)
                _tools_status=$?
                [ "$_tools_status" -le 1 ] || exit "$_tools_status"
                if [ "$_tools_status" = 0 ]; then
                    printf '%s\n' "$_tools_required" | awk -v package="$_tools_package" '$0!=package {print}'
                fi
            done) || return
            ;;
        *) return 1 ;;
    esac
    if [ -n "$_tools_dependents" ]; then
        printf 'Refusing removal: installed software depends on %s.\n' "$_tools_id" >&2; return 1
    fi
}

# Validate private directories without requiring the lifecycle library to be sourced.
_tools_safe_ancestor() (
    case $1 in /*) ;; *) printf '%s\n' 'Tool paths must be absolute.' >&2; return 1 ;; esac
    case $1 in *'/../'*|*'/..'|*'/./'*|*'/.'|*"$(printf '\t')"*|*'
'*) printf '%s\n' 'Unsafe tool path.' >&2; return 1 ;; esac
    _tools_parent=$(dirname "$1")
    while [ ! -d "$_tools_parent" ]; do
        [ ! -L "$_tools_parent" ] || { printf '%s\n' 'Broken symlink in tool path.' >&2; return 1; }
        [ "$_tools_parent" != / ] || return 1
        _tools_parent=$(dirname "$_tools_parent")
    done
    _tools_physical=$(CDPATH='' cd "$_tools_parent" && pwd -P) || return
    _tools_home=$(CDPATH='' cd "$HOME" && pwd -P) || return
    [ "$_tools_home" != / ] || return 1
    case "$_tools_physical/" in "$_tools_home/"*) ;; *) printf '%s\n' 'Tool path escapes HOME.' >&2; return 1 ;; esac
)
_tools_paths_safe() {
    _tools_safe_ancestor "$DOTFILES_CONFIG/tools" &&
        _tools_safe_ancestor "$DOTFILES_STATE/packages" &&
        _tools_safe_ancestor "${DOTFILES_BIN:-$HOME/.local/bin}/.dotfiles-check" || return
    for _tools_private in "$DOTFILES_CONFIG/tools" "$DOTFILES_STATE/packages" "$DOTFILES_STATE/tools.lock" "$DOTFILES_STATE/aliases.tsv"; do
        [ ! -L "$_tools_private" ] || { printf '%s\n' 'Refusing symlinked private tool state.' >&2; return 1; }
    done
}

_tools_hash() {
    if command -v sha256sum >/dev/null 2>&1; then sha256sum < "$1" | cut -d ' ' -f 1
    else shasum -a 256 < "$1" | cut -d ' ' -f 1; fi
}
_tools_app_shim() (
    umask 077
    mkdir -p "$DOTFILES_STATE" || return
    _tools_stage=$(mktemp "$_tools_bin/.$_tools_alias_command.XXXXXX") || return
    trap 'rm -f "$_tools_stage"' EXIT
    _tools_quoted=$(printf '%s' "$_tools_target" | sed "s/'/'\\\\''/g")
    printf '%s\n' '#!/bin/sh' "exec '$_tools_quoted' "'"$@"' > "$_tools_stage" || return
    chmod 755 "$_tools_stage" || return
    _tools_digest=$(_tools_hash "$_tools_stage") || return
    [ ! -e "$_tools_bin/$_tools_alias_command" ] && [ ! -L "$_tools_bin/$_tools_alias_command" ] || return 1
    mv "$_tools_stage" "$_tools_bin/$_tools_alias_command" || return
    printf '%s\t%s\t%s\n' "$1" "$_tools_alias_command" "$_tools_digest" >> "$DOTFILES_STATE/aliases.tsv"
)
_tools_remove_app_shim() (
    [ -f "$DOTFILES_STATE/aliases.tsv" ] || return 0
    _tools_alias_row=$(awk -F '\t' -v id="$1" '$1==id {row=$0} END {print row}' "$DOTFILES_STATE/aliases.tsv")
    [ -n "$_tools_alias_row" ] || return 0
    _tools_command=$(_tools_field "$_tools_alias_row" 2)
    _tools_digest=$(_tools_field "$_tools_alias_row" 3)
    case $_tools_command in code|firefox|google-chrome|jetbrains-toolbox|pgadmin4|orb|utmctl) ;; *) return 1 ;; esac
    _tools_path=${DOTFILES_BIN:-$HOME/.local/bin}/$_tools_command
    [ ! -L "$_tools_path" ] && [ -f "$_tools_path" ] || return 0
    if [ "$(_tools_hash "$_tools_path")" = "$_tools_digest" ]; then
        rm -f "$_tools_path" || return
        _tools_new=$(mktemp "$DOTFILES_STATE/aliases.XXXXXX") || return
        awk -F '\t' -v id="$1" '$1!=id' "$DOTFILES_STATE/aliases.tsv" > "$_tools_new" && mv "$_tools_new" "$DOTFILES_STATE/aliases.tsv"
    fi
)
