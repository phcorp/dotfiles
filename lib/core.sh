# Lifecycle functions. No private configuration is evaluated by this CLI.
# shellcheck disable=SC2153
say() { printf '%s\n' "$*"; }
fail() { printf 'dotfiles: %s\n' "$*" >&2; return 1; }
hash_file() {
    if [ -L "$1" ]; then printf 'link:%s\n' "$(readlink "$1")"; return; fi
    if [ ! -f "$1" ]; then printf 'missing\n'; return; fi
    if command -v sha256sum >/dev/null 2>&1; then sha256sum < "$1" | cut -d ' ' -f 1
    else shasum -a 256 < "$1" | cut -d ' ' -f 1; fi
}
cm() {
    chezmoi --source "$DOTFILES_SOURCE" --destination "$HOME" \
        --config "$DOTFILES_CONFIG/chezmoi.toml" --persistent-state "$DOTFILES_STATE/chezmoi.db" \
        --no-tty --no-pager "$@"
}
cm_config() {
    chezmoi --source "$DOTFILES_SOURCE/home/dot_config" --destination "$XDG_CONFIG_HOME" \
        --config "$DOTFILES_CONFIG/chezmoi.toml" --persistent-state "$DOTFILES_STATE/config.db" \
        --no-tty --no-pager "$@"
}
managed_paths() {
    cm managed --include files,symlinks --path-style absolute || return
    cm_config managed --include files,symlinks --path-style absolute || return
    printf '%s\n' "$HOME/.local/bin/dotfiles"
}
valid_paths() {
    # State is line-delimited; private paths must remain physically inside HOME.
    case "$HOME$DOTFILES_CONFIG$DOTFILES_STATE$DOTFILES_SOURCE$XDG_CONFIG_HOME" in
        *"$(printf '\t')"*|*'
'*) fail 'Paths containing tabs or newlines are unsupported.'; return 1 ;;
    esac
    case "$XDG_CONFIG_HOME/" in "$HOME/"*) ;; *) fail 'XDG_CONFIG_HOME must be within HOME.'; return 1 ;; esac
    [ "$HOME" != / ] || { fail 'HOME cannot be /.'; return 1; }
    for _private_dir in "$DOTFILES_CONFIG" "$DOTFILES_CONFIG/local" "$DOTFILES_STATE" "$DOTFILES_STATE/originals" "$DOTFILES_STATE/logs"; do
        [ ! -L "$_private_dir" ] || { fail 'Private state directories cannot be symlinks.'; return 1; }
        safe_ancestor "$_private_dir/placeholder" || return
    done
    # Reject link-based redirection of state files before any redirection/chmod.
    for _private_entry in "$DOTFILES_STATE"/* "$DOTFILES_CONFIG"/*; do
        [ ! -L "$_private_entry" ] || { fail 'Private state entries cannot be symlinks.'; return 1; }
    done
}
safe_ancestor() {
    _ancestor=$(dirname "$1")
    while [ ! -d "$_ancestor" ]; do
        [ ! -L "$_ancestor" ] || { fail 'Broken symlink in a managed directory.'; return 1; }
        [ "$_ancestor" != / ] || return 1
        _ancestor=$(dirname "$_ancestor")
    done
    _physical=$(CDPATH='' cd "$_ancestor" && pwd -P) || return
    _physical_home=$(CDPATH='' cd "$HOME" && pwd -P) || return
    case "$_physical/" in "$_physical_home/"*) ;; *) fail 'Managed directory symlink escapes HOME.'; return 1 ;; esac
}
safe_target() {
    case $1 in "$HOME/"*) ;; *) fail 'Managed target escaped HOME.'; return 1 ;; esac
    case ${1#"$HOME/"} in *../*|*/..|..) fail 'Unsafe managed target.'; return 1 ;; esac
    safe_ancestor "$1"
}
setup_state() {
    valid_paths || return
    mkdir -p "$DOTFILES_CONFIG/local" "$DOTFILES_STATE/originals" "$DOTFILES_STATE/logs" || return
    chmod 700 "$DOTFILES_CONFIG/local" "$DOTFILES_STATE" "$DOTFILES_STATE/originals" "$DOTFILES_STATE/logs" || return
    if [ ! -f "$DOTFILES_CONFIG/chezmoi.toml" ]; then printf 'progress = false\n' > "$DOTFILES_CONFIG/chezmoi.toml" || return; fi
    if [ ! -f "$DOTFILES_STATE/originals.list" ]; then : > "$DOTFILES_STATE/originals.list" || return; fi
}
lock_state() {
    _lifecycle_lock=$DOTFILES_STATE/lifecycle.lock
    if [ "${DOTFILES_UNLOCK_STALE:-0}" = 1 ]; then
        [ "$_action" = recover ] || { fail '--unlock-stale is only valid with recover.'; return 1; }
        if [ "$(lock_status "$_lifecycle_lock")" != absent ]; then lock_recover_stale "$_lifecycle_lock" || return; fi
    fi
    lock_acquire "$_lifecycle_lock" || { fail 'Lifecycle lock prevents this operation. Run dotfiles doctor for status and safe recovery instructions.'; return 1; }
    trap '_result=$?; printf "%s\t%s\t%s\n" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${_action:-operation}" "$_result" > "$DOTFILES_STATE/last-operation"; lock_release "$_lifecycle_lock" || :' EXIT
    trap 'exit 129' HUP
    trap 'exit 130' INT
    trap 'exit 143' TERM
}

check_owned() {
    [ -f "$DOTFILES_STATE/managed.tsv" ] || return 0
    _changed=0
    while IFS="$(printf '\t')" read -r _digest _path; do
        [ "$(hash_file "$_path")" = "$_digest" ] || { printf 'dotfiles: locally modified managed file: %s\n' "${_path#"$HOME/"}" >&2; _changed=1; }
    done < "$DOTFILES_STATE/managed.tsv"
    [ "$_changed" = 0 ] || [ "$DOTFILES_FORCE" = 1 ]
}
save_original() {
    _path=$1
    safe_target "$_path" || return
    _rel=${_path#"$HOME/"}
    if ! grep -Fxq "$_rel" "$DOTFILES_STATE/originals.list"; then
        if [ -e "$_path" ] || [ -L "$_path" ]; then
            [ ! -d "$_path" ] || [ -L "$_path" ] || { fail "Directory conflicts with managed file: $_rel"; return 1; }
            safe_ancestor "$DOTFILES_STATE/originals/$_rel" || return
            mkdir -p "$DOTFILES_STATE/originals/$(dirname "$_rel")" || return
            cp -Pp "$_path" "$DOTFILES_STATE/originals/$_rel" || return
        fi
        printf '%s\n' "$_rel" >> "$DOTFILES_STATE/originals.list" || return
    fi
}
restore_original() {
    _path=$1; _rel=${_path#"$HOME/"}
    safe_target "$_path" || return
    safe_ancestor "$DOTFILES_STATE/originals/$_rel" || return
    if [ -e "$DOTFILES_STATE/originals/$_rel" ] || [ -L "$DOTFILES_STATE/originals/$_rel" ]; then
        mkdir -p "$(dirname "$_path")" || return
        rm -f "$_path" || return
        cp -Pp "$DOTFILES_STATE/originals/$_rel" "$_path" || return
    else rm -f "$_path" || return; fi
}
save_selection() {
    [ -n "$DOTFILES_PROFILES" ] || return 0
    _profiles=$(printf '%s' "$DOTFILES_PROFILES" | tr ',' ' ')
    for _profile in $_profiles; do
        case $_profile in shell|runtimes|php|cloud|databases|desktop) ;; *) fail "Unknown profile: $_profile"; return 1 ;; esac
    done
    : > "$DOTFILES_CONFIG/tools.new"
    for _profile in $_profiles; do
        awk -F '\t' -v p="$_profile" '$1 !~ /^#/ && $6 == p {print $1}' "$DOTFILES_SOURCE/catalog.tsv" >> "$DOTFILES_CONFIG/tools.new"
    done
    : > "$DOTFILES_CONFIG/tools"
    sort -u "$DOTFILES_CONFIG/tools.new" > "$DOTFILES_CONFIG/tools.sorted"
    while IFS= read -r _tool; do
        if tools_supported "$_tool"; then printf '%s\n' "$_tool" >> "$DOTFILES_CONFIG/tools"
        else say "Unavailable on this platform: $_tool (not selected)."; fi
    done < "$DOTFILES_CONFIG/tools.sorted"
    rm "$DOTFILES_CONFIG/tools.sorted"
    rm "$DOTFILES_CONFIG/tools.new"
    printf '%s\n' "$DOTFILES_PROFILES" > "$DOTFILES_CONFIG/profiles"
}
migrate_git() {
    [ ! -L "$DOTFILES_CONFIG/local/gitconfig" ] || { fail 'Private Git configuration cannot be a symlink.'; return 1; }
    if [ -f "$HOME/.gitconfig" ] && [ ! -f "$DOTFILES_CONFIG/local/gitconfig" ]; then
        cp -p "$HOME/.gitconfig" "$DOTFILES_CONFIG/local/gitconfig"
        chmod 600 "$DOTFILES_CONFIG/local/gitconfig"
        # Git resolves relative includes beside the file; preserve their original base.
        git config --file "$DOTFILES_CONFIG/local/gitconfig" --get-regexp '^include.*\.path$' > "$DOTFILES_STATE/includes.tmp" || :
        while IFS=' ' read -r _key _value; do
            case $_value in /*|\~/*|'') ;; *) git config --file "$DOTFILES_CONFIG/local/gitconfig" --fixed-value --replace-all "$_key" "$HOME/$_value" "$_value" ;; esac
        done < "$DOTFILES_STATE/includes.tmp"
        rm -f "$DOTFILES_STATE/includes.tmp"
    fi
}
rotate_originals() {
    if [ ! -f "$DOTFILES_STATE/managed.tsv" ] && [ -s "$DOTFILES_STATE/originals.list" ]; then
        [ ! -d "$DOTFILES_STATE/transaction" ] || [ "${_transaction_open:-0}" = 1 ] || { fail 'Recover the interrupted installation before reinstalling.'; return 1; }
        _archive=$(mktemp -d "$DOTFILES_STATE/previous-install.XXXXXX") || return
        mv "$DOTFILES_STATE/originals" "$_archive/originals" || return
        mv "$DOTFILES_STATE/originals.list" "$_archive/originals.list" || return
        mkdir "$DOTFILES_STATE/originals" || return
        : > "$DOTFILES_STATE/originals.list" || return
    fi
}
apply_abort() {
    recover_files || { fail 'Rollback incomplete; transaction retained for recovery.'; return 1; }
    fail 'Apply failed; prior files restored.'
}
begin_transaction() {
    _transaction=$DOTFILES_STATE/transaction
    [ ! -e "$_transaction" ] || { fail 'Interrupted transaction detected. Run dotfiles recover.'; return 1; }
    mkdir -p "$_transaction/files" "$_transaction/metadata" || return
    printf '2\n' > "$_transaction/format" || return
    : > "$_transaction/paths" || return
    printf '%s\n' "$DOTFILES_STATE/managed.tsv" "$DOTFILES_STATE/applied-revision" \
        "$DOTFILES_CONFIG/tools" "$DOTFILES_CONFIG/profiles" "$DOTFILES_CONFIG/mode" \
        "$DOTFILES_STATE/originals.list" > "$_transaction/metadata.paths" || return
    _index=0
    while IFS= read -r _metadata_path; do
        _index=$((_index + 1))
        safe_target "$_metadata_path" || return
        [ ! -L "$_metadata_path" ] || { fail 'Transaction metadata cannot be a symlink.'; return 1; }
        if [ -f "$_metadata_path" ]; then cp -p "$_metadata_path" "$_transaction/metadata/$_index" || return; fi
    done < "$_transaction/metadata.paths"
    cp -RPp "$DOTFILES_STATE/originals" "$_transaction/originals.before" || return
    : > "$_transaction/metadata.ready" || return
    _transaction_open=1
}
commit_transaction() {
    : > "$_transaction/committed.new" || return
    mv "$_transaction/committed.new" "$_transaction/committed" || return
    rm -rf "$_transaction" || return
    _transaction_open=0
}
apply_files() {
    valid_paths || return
    check_owned || { fail 'Use private local overrides or explicitly repair --force after reviewing your edits.'; return 1; }
    [ "${_transaction_open:-0}" = 1 ] || begin_transaction || return
    managed_paths > "$DOTFILES_STATE/targets.unsorted" || { apply_abort; return 1; }
    sort -u "$DOTFILES_STATE/targets.unsorted" > "$DOTFILES_STATE/targets.new" || { apply_abort; return 1; }
    if [ -f "$DOTFILES_STATE/managed.tsv" ]; then cut -f2 "$DOTFILES_STATE/managed.tsv" >> "$DOTFILES_STATE/targets.new" || { apply_abort; return 1; }; fi
    sort -u "$DOTFILES_STATE/targets.new" > "$DOTFILES_STATE/targets.all" || { apply_abort; return 1; }
    while IFS= read -r _target; do
        save_original "$_target" || { apply_abort; return 1; }
        _relative=${_target#"$HOME/"}
        if [ -e "$_target" ] || [ -L "$_target" ]; then
            mkdir -p "$_transaction/files/$(dirname "$_relative")" || { apply_abort; return 1; }
            cp -Pp "$_target" "$_transaction/files/$_relative" || { apply_abort; return 1; }
        fi
        printf '%s\n' "$_target" >> "$_transaction/paths" || { apply_abort; return 1; }
    done < "$DOTFILES_STATE/targets.all"
    : > "$_transaction/files.ready" || { apply_abort; return 1; }
    if ! cm apply --force || ! cm_config apply --force; then apply_abort; return 1; fi
    mkdir -p "$HOME/.local/bin" || { apply_abort; return 1; }
    ln -snf "$DOTFILES_SOURCE/bin/dotfiles" "$HOME/.local/bin/dotfiles" || { apply_abort; return 1; }
    managed_paths > "$DOTFILES_STATE/targets.unsorted" || { apply_abort; return 1; }
    sort -u "$DOTFILES_STATE/targets.unsorted" > "$DOTFILES_STATE/targets.current" || { apply_abort; return 1; }
    while IFS= read -r _target; do
        if ! grep -Fxq "$_target" "$DOTFILES_STATE/targets.current"; then restore_original "$_target" || { apply_abort; return 1; }; fi
    done < "$_transaction/paths"
    : > "$DOTFILES_STATE/managed.new" || { apply_abort; return 1; }
    while IFS= read -r _target; do
        _new_hash=$(hash_file "$_target") || { apply_abort; return 1; }
        printf '%s\t%s\n' "$_new_hash" "$_target" >> "$DOTFILES_STATE/managed.new" || { apply_abort; return 1; }
    done < "$DOTFILES_STATE/targets.current"
    mv "$DOTFILES_STATE/managed.new" "$DOTFILES_STATE/managed.tsv" || { apply_abort; return 1; }
    if git -C "$DOTFILES_SOURCE" rev-parse HEAD > "$DOTFILES_STATE/applied-revision.new" 2>/dev/null; then
        mv "$DOTFILES_STATE/applied-revision.new" "$DOTFILES_STATE/applied-revision" || { apply_abort; return 1; }
    else rm -f "$DOTFILES_STATE/applied-revision.new"; fi
    rm -f "$DOTFILES_STATE/targets.new" "$DOTFILES_STATE/targets.all" "$DOTFILES_STATE/targets.current" "$DOTFILES_STATE/targets.unsorted" || { apply_abort; return 1; }
}
recover_files() {
    valid_paths || return
    _recovery=$DOTFILES_STATE/transaction
    [ -f "$_recovery/paths" ] || { fail 'No recovery transaction exists.'; return 1; }
    if [ -f "$_recovery/committed" ]; then
        rm -rf "$_recovery" || return
        _transaction_open=0
        say 'Completed transaction cleanup; committed files and revision retained.'; return 0
    fi
    # Check source and every path before restoring any files. Never discard new
    # manual commits or uncommitted source changes during interrupted sync recovery.
    if [ -f "$_recovery/source.before" ]; then
        _source_before=$(cat "$_recovery/source.before")
        _source_next=
        if [ -f "$_recovery/source.next" ]; then _source_next=$(cat "$_recovery/source.next"); fi
        case $_source_before in ''|*[!a-f0-9]*) fail 'Invalid source recovery revision; preserve the journal for review.'; return 1 ;; esac
        [ "${#_source_before}" = 40 ] || { fail 'Invalid source recovery revision; preserve the journal for review.'; return 1; }
        if [ -f "$_recovery/source.ready" ]; then
            case $_source_next in ''|*[!a-f0-9]*) fail 'Invalid candidate recovery revision; preserve the journal for review.'; return 1 ;; esac
            [ "${#_source_next}" = 40 ] || { fail 'Invalid candidate recovery revision; preserve the journal for review.'; return 1; }
        fi
        _source_current=$(git -C "$DOTFILES_SOURCE" rev-parse HEAD) || return
        if [ ! -f "$_recovery/source.ready" ] && [ "$_source_current" != "$_source_before" ]; then fail 'Source changed before journal preparation completed; preserve it for review.'; return 1; fi
        case $_source_current in "$_source_before"|"$_source_next") ;; *) fail 'Source changed since interruption; review the journal before recovery.'; return 1 ;; esac
        _source_status=$(git -c core.fsmonitor=false -C "$DOTFILES_SOURCE" status --porcelain) || { fail 'Cannot inspect source status; preserve it before recovery.'; return 1; }
        [ -z "$_source_status" ] || { fail 'Source has local changes; preserve them before recovery.'; return 1; }
        git -C "$DOTFILES_SOURCE" cat-file -e "$_source_before^{commit}" || return
    fi
    while IFS= read -r _target; do
        safe_target "$_target" || return
        [ ! -d "$_target" ] || [ -L "$_target" ] || { fail 'Recovery target is a directory; preserve it before recovery.'; return 1; }
        safe_ancestor "$_recovery/files/${_target#"$HOME/"}" || return
    done < "$_recovery/paths"
    if [ -f "$_recovery/metadata.ready" ]; then
        while IFS= read -r _metadata_path; do
            case $_metadata_path in "$DOTFILES_STATE/managed.tsv"|"$DOTFILES_STATE/applied-revision"|"$DOTFILES_CONFIG/tools"|"$DOTFILES_CONFIG/profiles"|"$DOTFILES_CONFIG/mode"|"$DOTFILES_STATE/originals.list") ;; *) fail 'Invalid recovery metadata path.'; return 1 ;; esac
            safe_target "$_metadata_path" || return
            if [ -L "$_metadata_path" ] || [ -d "$_metadata_path" ]; then fail 'Recovery metadata path changed; manual review required.'; return 1; fi
        done < "$_recovery/metadata.paths"
    fi
    while IFS= read -r _target; do
        _relative=${_target#"$HOME/"}
        rm -f "$_target" || return
        if [ -e "$_recovery/files/$_relative" ] || [ -L "$_recovery/files/$_relative" ]; then
            mkdir -p "$(dirname "$_target")" || return
            cp -Pp "$_recovery/files/$_relative" "$_target" || return
        fi
    done < "$_recovery/paths"
    if [ -f "$_recovery/metadata.ready" ]; then
        _index=0
        while IFS= read -r _metadata_path; do
            _index=$((_index + 1))
            if [ -f "$_recovery/metadata/$_index" ]; then cp -p "$_recovery/metadata/$_index" "$_metadata_path" || return
            else rm -f "$_metadata_path" || return; fi
        done < "$_recovery/metadata.paths"
        if [ -d "$_recovery/originals.before" ]; then
            rm -rf "$DOTFILES_STATE/originals" || return
            cp -RPp "$_recovery/originals.before" "$DOTFILES_STATE/originals" || return
        fi
    elif [ -f "$_recovery/managed.before" ]; then
        cp -p "$_recovery/managed.before" "$DOTFILES_STATE/managed.tsv" || return
    fi
    if [ -f "$_recovery/source.before" ]; then
        git -c core.hooksPath=/dev/null -c core.fsmonitor=false -C "$DOTFILES_SOURCE" reset --hard --quiet "$_source_before" || return
    fi
    rm -rf "$_recovery" || return
    rm -f "$DOTFILES_STATE/applied-revision.new" "$DOTFILES_STATE/managed.new" "$DOTFILES_STATE/targets.new" "$DOTFILES_STATE/targets.all" "$DOTFILES_STATE/targets.current" "$DOTFILES_STATE/targets.unsorted" || return
    _transaction_open=0
    say 'Recovered prior files, ownership, and revision metadata.'
}

scheduler_target() {
    safe_target "$1" || return
    [ ! -L "$1" ] || { fail 'Scheduler files cannot be symlinks.'; return 1; }
}
xml_value() { printf '%s' "$1" | sed 's/\&/\&amp;/g;s/</\&lt;/g;s/>/\&gt;/g'; }
sync_disable() {
    # A disposable/uninstalled HOME does not own the user's global scheduler.
    if [ ! -f "$DOTFILES_CONFIG/sync-enabled" ]; then
        case $(uname -s) in
            Darwin) [ -f "$HOME/Library/LaunchAgents/com.phcorp.dotfiles.plist" ] || return 0 ;;
            Linux) if [ ! -f "$XDG_CONFIG_HOME/systemd/user/dotfiles-sync.timer" ] && [ ! -f "$XDG_CONFIG_HOME/systemd/user/dotfiles-sync.service" ]; then return 0; fi ;;
        esac
    fi
    case $(uname -s) in
        Darwin)
            scheduler_target "$HOME/Library/LaunchAgents/com.phcorp.dotfiles.plist" || return
            launchctl bootout "gui/$(id -u)/com.phcorp.dotfiles" >/dev/null 2>&1 || :
            rm -f "$HOME/Library/LaunchAgents/com.phcorp.dotfiles.plist" ;;
        Linux)
            scheduler_target "$XDG_CONFIG_HOME/systemd/user/dotfiles-sync.timer" || return
            scheduler_target "$XDG_CONFIG_HOME/systemd/user/dotfiles-sync.service" || return
            if command -v systemctl >/dev/null 2>&1; then systemctl --user disable --now dotfiles-sync.timer >/dev/null 2>&1 || :; fi
            rm -f "$XDG_CONFIG_HOME/systemd/user/dotfiles-sync.timer" "$XDG_CONFIG_HOME/systemd/user/dotfiles-sync.service"
            if command -v crontab >/dev/null 2>&1; then
                (crontab -l 2>/dev/null || :) | sed '/# phcorp-dotfiles-sync$/d' > "$DOTFILES_STATE/cron.tmp"
                crontab "$DOTFILES_STATE/cron.tmp"; rm "$DOTFILES_STATE/cron.tmp"
            fi ;;
    esac
    rm -f "$DOTFILES_CONFIG/sync-enabled"
}
sync_enable() {
    _cli=$HOME/.local/bin/dotfiles
    case $(uname -s) in
        Darwin)
            scheduler_target "$HOME/Library/LaunchAgents/com.phcorp.dotfiles.plist" || return
            mkdir -p "$HOME/Library/LaunchAgents" || return
            # XML-escape machine paths without writing private data into the repository.
            _xml_cli=$(xml_value "$_cli")
            _xml_home=$(xml_value "$HOME")
            _xml_source=$(xml_value "$DOTFILES_SOURCE")
            _xml_config=$(xml_value "$DOTFILES_CONFIG")
            _xml_state=$(xml_value "$DOTFILES_STATE")
            _xml_xdg_config=$(xml_value "$XDG_CONFIG_HOME")
            _xml_xdg_state=$(xml_value "$XDG_STATE_HOME")
            cat > "$HOME/Library/LaunchAgents/com.phcorp.dotfiles.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>com.phcorp.dotfiles</string>
<key>ProgramArguments</key><array><string>$_xml_cli</string><string>sync</string><string>--non-interactive</string></array>
<key>EnvironmentVariables</key><dict><key>HOME</key><string>$_xml_home</string><key>DOTFILES_SOURCE</key><string>$_xml_source</string><key>DOTFILES_CONFIG</key><string>$_xml_config</string><key>DOTFILES_STATE</key><string>$_xml_state</string><key>XDG_CONFIG_HOME</key><string>$_xml_xdg_config</string><key>XDG_STATE_HOME</key><string>$_xml_xdg_state</string><key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string></dict>
<key>StartInterval</key><integer>3600</integer>
<key>RunAtLoad</key><true/>
</dict></plist>
EOF
            launchctl bootout "gui/$(id -u)/com.phcorp.dotfiles" >/dev/null 2>&1 || :
            launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.phcorp.dotfiles.plist" ;;
        Linux)
            scheduler_target "$XDG_CONFIG_HOME/systemd/user/dotfiles-sync.timer" || return
            scheduler_target "$XDG_CONFIG_HOME/systemd/user/dotfiles-sync.service" || return
            if command -v systemctl >/dev/null 2>&1 && systemctl --user show-environment >/dev/null 2>&1; then
                # systemd expands specifiers and environment syntax even inside quotes.
                case "$HOME$DOTFILES_SOURCE$DOTFILES_CONFIG$DOTFILES_STATE$XDG_CONFIG_HOME$XDG_STATE_HOME" in *'"'*|*'%'*|*'$'*|*\\*) fail 'Systemd scheduler paths cannot contain quotes, percent signs, dollar signs, or backslashes.'; return 1 ;; esac
                mkdir -p "$XDG_CONFIG_HOME/systemd/user"
                cat > "$XDG_CONFIG_HOME/systemd/user/dotfiles-sync.service" <<EOF
[Unit]
Description=Pull validated public dotfiles
[Service]
Type=oneshot
ExecStart="$_cli" sync --non-interactive
Environment="PATH=$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"
Environment="DOTFILES_SOURCE=$DOTFILES_SOURCE" "DOTFILES_CONFIG=$DOTFILES_CONFIG" "DOTFILES_STATE=$DOTFILES_STATE" "XDG_CONFIG_HOME=$XDG_CONFIG_HOME" "XDG_STATE_HOME=$XDG_STATE_HOME"
EOF
                cat > "$XDG_CONFIG_HOME/systemd/user/dotfiles-sync.timer" <<'EOF'
[Unit]
Description=Hourly dotfiles synchronization
[Timer]
OnBootSec=5min
OnUnitActiveSec=1h
Persistent=true
[Install]
WantedBy=timers.target
EOF
                systemctl --user daemon-reload
                systemctl --user enable --now dotfiles-sync.timer
            elif command -v crontab >/dev/null 2>&1; then
                case "$HOME$DOTFILES_SOURCE$DOTFILES_CONFIG$DOTFILES_STATE$XDG_CONFIG_HOME$XDG_STATE_HOME" in *"'"*|*'%'*) fail 'Cron paths containing quotes or percent signs are unsupported.'; return 1 ;; esac
                (crontab -l 2>/dev/null || :) | sed '/# phcorp-dotfiles-sync$/d' > "$DOTFILES_STATE/cron.tmp"
                printf "17 * * * * PATH='%s/.local/bin:/usr/local/bin:/usr/bin:/bin' DOTFILES_SOURCE='%s' DOTFILES_CONFIG='%s' DOTFILES_STATE='%s' XDG_CONFIG_HOME='%s' XDG_STATE_HOME='%s' '%s' sync --non-interactive >/dev/null 2>&1 # phcorp-dotfiles-sync\n" "$HOME" "$DOTFILES_SOURCE" "$DOTFILES_CONFIG" "$DOTFILES_STATE" "$XDG_CONFIG_HOME" "$XDG_STATE_HOME" "$_cli" >> "$DOTFILES_STATE/cron.tmp"
                crontab "$DOTFILES_STATE/cron.tmp"; rm "$DOTFILES_STATE/cron.tmp"
            else fail 'No user systemd or cron scheduler available; install one before enabling sync.'; return 1; fi ;;
        *) fail 'Unsupported scheduler platform.'; return 1 ;;
    esac
    : > "$DOTFILES_CONFIG/sync-enabled"
}
ci_passed() {
    if [ "${DOTFILES_TESTING:-0}" = 1 ] && [ "${DOTFILES_SYNC_SKIP_CI:-0}" = 1 ]; then return 0; fi
    ci_verify_commit "$1"
}

sync_repository() {
    check_owned || return 1
    settings_check_origin "$DOTFILES_SOURCE" || return
    _source_status=$(git -c core.fsmonitor=false -C "$DOTFILES_SOURCE" status --porcelain) || { fail 'Cannot inspect source status; sync stopped.'; return 1; }
    [ -z "$_source_status" ] || { fail 'Source checkout has uncommitted changes; sync stopped.'; return 1; }
    _old=$(git -C "$DOTFILES_SOURCE" rev-parse HEAD)
    GIT_TERMINAL_PROMPT=0 git -c core.hooksPath=/dev/null -c core.fsmonitor=false -C "$DOTFILES_SOURCE" fetch --quiet origin "$DOTFILES_BRANCH" || { fail 'Fetch failed; current configuration retained.'; return 1; }
    _next=$(git -C "$DOTFILES_SOURCE" rev-parse "refs/remotes/origin/$DOTFILES_BRANCH")
    git -C "$DOTFILES_SOURCE" merge-base --is-ancestor "$_old" "$_next" || { fail 'History diverged; manual review required.'; return 1; }
    ci_passed "$_next" || { fail 'Successful Verify CI unavailable; current configuration retained.'; return 1; }
    [ "$_old" != "$_next" ] || { say 'Already synchronized.'; return 0; }
    [ "${_transaction_open:-0}" = 1 ] || begin_transaction || return
    printf '%s\n' "$_old" > "$_transaction/source.before.new" && mv "$_transaction/source.before.new" "$_transaction/source.before" || return
    printf '%s\n' "$_next" > "$_transaction/source.next.new" && mv "$_transaction/source.next.new" "$_transaction/source.next" || return
    : > "$_transaction/source.ready.new" && mv "$_transaction/source.ready.new" "$_transaction/source.ready" || return
    if ! git -c core.hooksPath=/dev/null -c core.fsmonitor=false -C "$DOTFILES_SOURCE" merge --ff-only --quiet "$_next"; then apply_abort; return 1; fi
    if ! apply_files; then
        [ ! -d "$DOTFILES_STATE/transaction" ] || recover_files || return
        fail 'Deployment failed; source revision restored.'; return 1
    fi
    commit_transaction || return
    say "Synchronized revision $_next."
}
publish_repository() (
    [ $# -gt 0 ] || { fail 'Usage: dotfiles publish "commit message"'; return 1; }
    settings_check_origin "$DOTFILES_SOURCE" || return
    [ "$(git -C "$DOTFILES_SOURCE" symbolic-ref --short HEAD)" = "$DOTFILES_BRANCH" ] || { fail 'Source is not on the configured publication branch; review it before publishing.'; return 1; }
    settings_publish_git_env || return
    command -v gitleaks >/dev/null 2>&1 || tools_ensure gitleaks || { fail 'Gitleaks is required before publishing.'; return 1; }
    "$DOTFILES_SOURCE/scripts/check-public.sh" || return
    (cd "$DOTFILES_SOURCE" && gitleaks dir --redact --no-banner . && gitleaks git --redact --no-banner) || return
    git -C "$DOTFILES_SOURCE" add -- . || return
    git -C "$DOTFILES_SOURCE" commit -m "$1" || return
    GIT_TERMINAL_PROMPT=0 git -C "$DOTFILES_SOURCE" push origin "HEAD:refs/heads/$DOTFILES_BRANCH"
)

doctor() {
    _status=0
    _doctor_lock=$(lock_status "$DOTFILES_STATE/lifecycle.lock")
    case $_doctor_lock in
        active) say 'Lifecycle lock active: matching PID, host, and process start. Do not remove it.'; _status=1 ;;
        stale) say 'Lifecycle lock stale: its owner exited or its PID was reused. Run dotfiles recover --unlock-stale to reclaim it explicitly.'; _status=1 ;;
        unknown) say 'Lifecycle lock owner cannot be verified (legacy, foreign host, or inaccessible process). Review its private owner metadata and original host before manual recovery; it will not be removed automatically.'; _status=1 ;;
    esac
    for _required in git chezmoi curl jq; do
        command -v "$_required" >/dev/null 2>&1 || { say "Missing prerequisite: $_required"; _status=1; }
    done
    if [ -f "$DOTFILES_STATE/managed.tsv" ]; then
        check_owned || _status=1
        say 'Managed configuration installed.'
    else say 'Managed configuration not installed.'; _status=1; fi
    if [ -f "$DOTFILES_CONFIG/sync-enabled" ]; then
        case $(uname -s) in
            Darwin) launchctl print "gui/$(id -u)/com.phcorp.dotfiles" >/dev/null 2>&1 || _status=1 ;;
            Linux) if command -v systemctl >/dev/null 2>&1 && systemctl --user is-active dotfiles-sync.timer >/dev/null 2>&1; then :
                elif command -v crontab >/dev/null 2>&1 && crontab -l 2>/dev/null | grep -q '# phcorp-dotfiles-sync$'; then :
                else _status=1; fi ;;
        esac
        say 'Automatic sync configured (hourly).'
    else say 'Automatic sync disabled.'; fi
    if [ -r "$DOTFILES_STATE/last-operation" ]; then
        IFS="$(printf '\t')" read -r _when _operation _result < "$DOTFILES_STATE/last-operation"
        say "Last lifecycle operation: $_operation at $_when (exit $_result)."
    fi
    if [ -f "$DOTFILES_CONFIG/tools" ]; then
        _missing=0
        while IFS= read -r _tool; do
            _record=$(_tools_row "$_tool") || { say 'Invalid selected tool.'; _status=1; continue; }
            _tools_available "$_record" || _missing=$((_missing + 1))
        done < "$DOTFILES_CONFIG/tools"
        say "Selected tools pending first-use installation: $_missing."
    fi
    [ ! -d "$DOTFILES_STATE/transaction" ] || { say 'Interrupted apply: run dotfiles recover.'; _status=1; }
    return "$_status"
}
uninstall_files() {
    valid_paths || return
    sync_disable || return
    [ -f "$DOTFILES_STATE/managed.tsv" ] || { say 'No installed files to remove.'; return; }
    _skipped=0
    : > "$DOTFILES_STATE/remaining.tsv"
    while IFS="$(printf '\t')" read -r _digest _target; do
        if [ "$(hash_file "$_target")" = "$_digest" ]; then restore_original "$_target" || return
        else
            printf '%s\t%s\n' "$_digest" "$_target" >> "$DOTFILES_STATE/remaining.tsv"
            say "Preserved modified file: ${_target#"$HOME/"}"; _skipped=1
        fi
    done < "$DOTFILES_STATE/managed.tsv"
    if [ "$_skipped" = 0 ]; then rm "$DOTFILES_STATE/managed.tsv" "$DOTFILES_STATE/remaining.tsv"
    else mv "$DOTFILES_STATE/remaining.tsv" "$DOTFILES_STATE/managed.tsv"; fi
    say 'Private overrides, backups, and installed tools retained.'
    [ "$_skipped" = 0 ]
}
usage() {
    cat <<'EOF'
dotfiles wizard
dotfiles install|repair|update|uninstall [--non-interactive] [--dry-run]
         [--profiles shell,runtimes,php,cloud,databases,desktop] [--sync] [--force]
dotfiles tools list|ensure|install|update|remove [tool]
dotfiles apps list|install|update|remove [app|all] [--non-interactive] [--dry-run]
dotfiles sync [--non-interactive] | sync enable|disable
dotfiles publish "commit message" | doctor | recover [--unlock-stale]
dotfiles mode interactive|non-interactive
EOF
}
main() {
    _action=${1:-wizard}; [ $# = 0 ] || shift
    # The explicit wizard is interactive even when first-use installs are unattended.
    [ "$_action" != wizard ] || DOTFILES_MODE=interactive
    _sub=; _arg=
    case $_action in tools|apps|sync|mode) if [ $# -gt 0 ]; then case $1 in --*) ;; *) _sub=$1; shift ;; esac; fi ;;
        publish) _arg=${1:-}; [ $# = 0 ] || shift ;; esac
    while [ $# -gt 0 ]; do
        case $1 in
            --non-interactive) DOTFILES_MODE=non-interactive ;;
            --dry-run) DOTFILES_DRY_RUN=1 ;;
            --force) DOTFILES_FORCE=1 ;;
            --unlock-stale) DOTFILES_UNLOCK_STALE=1 ;;
            --sync) DOTFILES_SYNC_ENABLE=1 ;;
            --profiles) shift; [ $# -gt 0 ] || { fail '--profiles needs a value'; return 1; }; DOTFILES_PROFILES=$1 ;;
            --help|-h) usage; return ;;
            *) if { [ "$_action" = tools ] || [ "$_action" = apps ]; } && [ -z "$_arg" ]; then _arg=$1; else fail "Unknown argument: $1"; return 1; fi ;;
        esac
        shift
    done
    [ "$_action" != wizard ] || { wizard; return; }
    case $_action in --help|-h|help) usage; return ;; esac
    valid_paths
    if [ "$DOTFILES_DRY_RUN" = 1 ]; then
        preview; return
    fi
    case $_action in
        tools) setup_state; case $_sub in list) tools_list ;; ensure) tools_ensure "$_arg" ;; install) tools_install "$_arg" ;; update) tools_update "$_arg" ;; remove) tools_remove "$_arg" ;; *) usage; return 1 ;; esac ;;
        apps) setup_state; apps_action "$_sub" "${_arg:-all}" ;;
        doctor) doctor ;;
        mode) case $_sub in interactive|non-interactive) setup_state; printf '%s\n' "$_sub" > "$DOTFILES_CONFIG/mode" ;; *) fail 'Choose interactive or non-interactive'; return 1 ;; esac ;;
        install|repair|update|uninstall|recover|sync|publish)
            setup_state; lock_state
            case $_action in
                install) [ -n "$DOTFILES_PROFILES" ] || [ -f "$DOTFILES_CONFIG/tools" ] || DOTFILES_PROFILES=shell
                    begin_transaction || return
                    if ! { printf '%s\n' "$DOTFILES_MODE" > "$DOTFILES_CONFIG/mode" && rotate_originals && save_selection && migrate_git && apply_files; }; then
                        [ ! -d "$DOTFILES_STATE/transaction" ] || recover_files || return
                        return 1
                    fi
                    commit_transaction || return
                    if [ "${DOTFILES_TESTING:-0}" != 1 ] && [ -w "$DOTFILES_SOURCE/.git/config" ]; then
                        git -C "$DOTFILES_SOURCE" config core.hooksPath "$DOTFILES_SOURCE/scripts/git-hooks"
                    fi
                    [ "$DOTFILES_SYNC_ENABLE" = 0 ] || sync_enable
                    say 'Installed. Selected tools install on first use; use tools install to provision eagerly.' ;;
                repair) begin_transaction || return; if ! { save_selection && apply_files; }; then [ ! -d "$DOTFILES_STATE/transaction" ] || recover_files || return; return 1; fi; commit_transaction || return; say 'Configuration repaired.' ;;
                update) begin_transaction || return
                    if ! { save_selection && sync_repository; }; then [ ! -d "$DOTFILES_STATE/transaction" ] || recover_files || return; return 1; fi
                    [ "${_transaction_open:-0}" = 0 ] || commit_transaction ;;
                uninstall) uninstall_files ;;
                recover) if [ -d "$DOTFILES_STATE/transaction" ]; then recover_files
                    elif [ "${DOTFILES_UNLOCK_STALE:-0}" = 1 ]; then say 'No abandoned lock or file transaction requires further recovery.'
                    else fail 'No recovery transaction exists.'; return 1; fi ;;
                sync) case $_sub in enable) sync_enable ;; disable) sync_disable ;; '') sync_repository ;; *) fail 'Unknown sync action'; return 1 ;; esac ;;
                publish) publish_repository "$_arg" ;;
            esac ;;
        *) usage; return 1 ;;
    esac
}
wizard() {
    if [ "$DOTFILES_MODE" != interactive ] || [ ! -r /dev/tty ] || [ ! -w /dev/tty ]; then
        fail 'Wizard requires a terminal; use scriptable subcommands.'; return 1
    fi
    printf 'Dotfiles: 1 install, 2 update, 3 repair, 4 uninstall, 5 enable sync, 6 disable sync, 7 install apps, 8 update apps, 9 remove owned apps\nChoice [1]: ' > /dev/tty
    IFS= read -r _choice < /dev/tty
    case ${_choice:-1} in
        1)
            printf 'Profiles (comma-separated: shell,runtimes,php,cloud,databases,desktop) [shell]: ' > /dev/tty
            IFS= read -r _profiles < /dev/tty
            main install --profiles "${_profiles:-shell}"
            printf 'Install selected tools now? [y/N]: ' > /dev/tty; IFS= read -r _eager < /dev/tty
            if [ "$_eager" = y ] || [ "$_eager" = Y ]; then
                while IFS= read -r _tool; do tools_install "$_tool" || say "Could not install $_tool; use doctor/tools install later."; done < "$DOTFILES_CONFIG/tools"
            fi
            printf 'Enable hourly pull synchronization? [Y/n]: ' > /dev/tty; IFS= read -r _sync < /dev/tty
            case $_sync in n|N) ;; *) sync_enable ;; esac ;;
        2)
            main update
            printf 'Upgrade tools installed by dotfiles? [y/N]: ' > /dev/tty; IFS= read -r _upgrade < /dev/tty
            case $_upgrade in y|Y)
                if [ -f "$DOTFILES_STATE/packages" ]; then
                    while IFS="$(printf '\t')" read -r _tool _manager _package _ownership; do
                        tools_update "$_tool" || say "Could not upgrade $_tool; current installation retained."
                    done < "$DOTFILES_STATE/packages"
                fi ;; esac ;;
        3) main repair ;;
        4) printf 'Restore managed files and retain private backups/tools? [y/N]: ' > /dev/tty; IFS= read -r _confirm < /dev/tty
            case $_confirm in y|Y) main uninstall ;; *) say 'Cancelled.' ;; esac ;;
        5) main sync enable ;; 6) main sync disable ;;
        7) main apps install ;;
        8) main apps update ;;
        9) printf 'Remove desktop apps installed by dotfiles? Existing apps and app data are retained. [y/N]: ' > /dev/tty
            IFS= read -r _confirm < /dev/tty
            case $_confirm in y|Y) main apps remove ;; *) say 'Cancelled.' ;; esac ;;
        *) fail 'Invalid wizard choice'; return 1 ;;
    esac
}

# Batch desktop operations use saved selections; removal uses the ownership ledger.
apps_action() (
    _apps_action=$1; _apps_target=$2
    case $_apps_action in list) awk -F '\t' 'NR==1 || $6=="desktop"' "$DOTFILES_SOURCE/catalog.tsv"; return ;; install|update|remove) ;; *) fail 'Choose apps list, install, update, or remove'; return 1 ;; esac
    if [ "$_apps_target" != all ]; then
        _apps_record=$(_tools_row "$_apps_target") || return
        [ "$(_tools_field "$_apps_record" 6)" = desktop ] || { fail 'This tool is not a desktop app.'; return 1; }
        _apps_ids=$_apps_target
    elif [ "$_apps_action" = remove ]; then
        [ -f "$DOTFILES_STATE/packages" ] || return 0
        _apps_ids=$(awk -F '\t' 'NR==FNR {if ($6=="desktop") app[$1]=1; next} $1 in app && $4=="created-by-dotfiles" {print $1}' "$DOTFILES_SOURCE/catalog.tsv" "$DOTFILES_STATE/packages")
    else
        [ -f "$DOTFILES_CONFIG/tools" ] || { fail 'Select the desktop profile with install or repair first.'; return 1; }
        _apps_ids=$(awk -F '\t' 'NR==FNR {if ($6=="desktop") app[$1]=1; next} $1 in app {print $1}' "$DOTFILES_SOURCE/catalog.tsv" "$DOTFILES_CONFIG/tools")
    fi
    _apps_failed=0
    for _apps_id in $_apps_ids; do
        case $_apps_action in install) tools_install "$_apps_id" ;; update) tools_update "$_apps_id" ;; remove) tools_remove "$_apps_id" ;; esac || _apps_failed=1
    done
    return "$_apps_failed"
)
