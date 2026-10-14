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
    mkdir "$DOTFILES_STATE/lifecycle.lock" 2>/dev/null || { fail 'Another lifecycle operation is running. Remove the lock only after confirming it is stale.'; return 1; }
    trap '_result=$?; printf "%s\t%s\t%s\n" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${_action:-operation}" "$_result" > "$DOTFILES_STATE/last-operation"; rmdir "$DOTFILES_STATE/lifecycle.lock" 2>/dev/null || :' EXIT
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
            case $_value in /*|'~/'*|'') ;; *) git config --file "$DOTFILES_CONFIG/local/gitconfig" --fixed-value --replace-all "$_key" "$HOME/$_value" "$_value" ;; esac
        done < "$DOTFILES_STATE/includes.tmp"
        rm -f "$DOTFILES_STATE/includes.tmp"
    fi
}
rotate_originals() {
    if [ ! -f "$DOTFILES_STATE/managed.tsv" ] && [ -s "$DOTFILES_STATE/originals.list" ]; then
        [ ! -d "$DOTFILES_STATE/transaction" ] || { fail 'Recover the interrupted installation before reinstalling.'; return 1; }
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
apply_files() {
    valid_paths || return
    check_owned || { fail 'Use private local overrides or explicitly repair --force after reviewing your edits.'; return 1; }
    managed_paths > "$DOTFILES_STATE/targets.unsorted" || return
    sort -u "$DOTFILES_STATE/targets.unsorted" > "$DOTFILES_STATE/targets.new" || return
    if [ -f "$DOTFILES_STATE/managed.tsv" ]; then cut -f2 "$DOTFILES_STATE/managed.tsv" >> "$DOTFILES_STATE/targets.new" || return; fi
    sort -u "$DOTFILES_STATE/targets.new" > "$DOTFILES_STATE/targets.all" || return
    _transaction=$DOTFILES_STATE/transaction
    [ ! -e "$_transaction" ] || { fail 'Interrupted transaction detected. Run dotfiles recover.'; return 1; }
    mkdir -p "$_transaction/files" || return
    : > "$_transaction/paths" || return
    if [ -f "$DOTFILES_STATE/managed.tsv" ]; then cp -p "$DOTFILES_STATE/managed.tsv" "$_transaction/managed.before" || return; fi
    while IFS= read -r _target; do
        save_original "$_target" || { apply_abort; return 1; }
        _relative=${_target#"$HOME/"}
        if [ -e "$_target" ] || [ -L "$_target" ]; then
            mkdir -p "$_transaction/files/$(dirname "$_relative")" || { apply_abort; return 1; }
            cp -Pp "$_target" "$_transaction/files/$_relative" || { apply_abort; return 1; }
        fi
        printf '%s\n' "$_target" >> "$_transaction/paths" || { apply_abort; return 1; }
    done < "$DOTFILES_STATE/targets.all"
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
    git -C "$DOTFILES_SOURCE" rev-parse HEAD > "$DOTFILES_STATE/applied-revision" 2>/dev/null || :
    rm -rf "$_transaction" || return
    rm -f "$DOTFILES_STATE/targets.new" "$DOTFILES_STATE/targets.all" "$DOTFILES_STATE/targets.current" "$DOTFILES_STATE/targets.unsorted" || return
}
recover_files() {
    valid_paths || return
    [ -f "$DOTFILES_STATE/transaction/paths" ] || { fail 'No recovery transaction exists.'; return 1; }
    # Validate the whole transaction before restoring any target.
    while IFS= read -r _target; do
        safe_target "$_target" || return
        safe_ancestor "$DOTFILES_STATE/transaction/files/${_target#"$HOME/"}" || return
    done < "$DOTFILES_STATE/transaction/paths"
    while IFS= read -r _target; do
        _relative=${_target#"$HOME/"}
        rm -f "$_target" || return
        if [ -e "$DOTFILES_STATE/transaction/files/$_relative" ] || [ -L "$DOTFILES_STATE/transaction/files/$_relative" ]; then
            mkdir -p "$(dirname "$_target")" || return
            cp -Pp "$DOTFILES_STATE/transaction/files/$_relative" "$_target" || return
        fi
    done < "$DOTFILES_STATE/transaction/paths"
    if [ -f "$DOTFILES_STATE/transaction/managed.before" ]; then
        cp -p "$DOTFILES_STATE/transaction/managed.before" "$DOTFILES_STATE/managed.tsv" || return
    else rm -f "$DOTFILES_STATE/managed.tsv" || return; fi
    rm -rf "$DOTFILES_STATE/transaction" || return
    say 'Recovered prior file contents.'
}
scheduler_target() {
    safe_target "$1" || return
    [ ! -L "$1" ] || { fail 'Scheduler files cannot be symlinks.'; return 1; }
}
xml_value() { printf '%s' "$1" | sed 's/\&/\&amp;/g;s/</\&lt;/g;s/>/\&gt;/g'; }
sync_disable() {
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
    _sha=$1
    # Anonymous public API; require the complete Verify workflow, not a single job.
    curl -fsSL --connect-timeout 10 --max-time 30 \
        "https://api.github.com/repos/phcorp/dotfiles/actions/runs?head_sha=$_sha&status=completed&per_page=100" \
        -o "$DOTFILES_STATE/ci.json" || return 1
    command -v jq >/dev/null 2>&1 || { fail 'jq is required to validate synchronization CI.'; return 1; }
    jq -e --arg sha "$_sha" '[.workflow_runs[] | select(.name == "Verify" and .path == ".github/workflows/verify.yml" and .event == "push" and .head_branch == "master" and .head_sha == $sha)] | sort_by(.run_number) | last | .conclusion == "success"' "$DOTFILES_STATE/ci.json" >/dev/null
}
sync_repository() {
    check_owned || return 1
    [ -z "$(git -C "$DOTFILES_SOURCE" status --porcelain)" ] || { fail 'Source checkout has uncommitted changes; sync stopped.'; return 1; }
    _old=$(git -C "$DOTFILES_SOURCE" rev-parse HEAD)
    GIT_TERMINAL_PROMPT=0 git -C "$DOTFILES_SOURCE" fetch --quiet origin master || { fail 'Fetch failed; current configuration retained.'; return 1; }
    _next=$(git -C "$DOTFILES_SOURCE" rev-parse origin/master)
    git -C "$DOTFILES_SOURCE" merge-base --is-ancestor "$_old" "$_next" || { fail 'History diverged; manual review required.'; return 1; }
    ci_passed "$_next" || { fail 'Successful Verify CI unavailable; current configuration retained.'; return 1; }
    [ "$_old" != "$_next" ] || { say 'Already synchronized.'; return 0; }
    git -C "$DOTFILES_SOURCE" merge --ff-only --quiet "$_next"
    if ! apply_files; then
        git -C "$DOTFILES_SOURCE" reset --hard --quiet "$_old"
        fail 'Deployment failed; source revision restored.'; return 1
    fi
    say "Synchronized revision $_next."
}
publish_repository() {
    [ $# -gt 0 ] || { fail 'Usage: dotfiles publish "commit message"'; return 1; }
    command -v gitleaks >/dev/null 2>&1 || tools_ensure gitleaks || { fail 'Gitleaks is required before publishing.'; return 1; }
    "$DOTFILES_SOURCE/scripts/check-public.sh"
    (cd "$DOTFILES_SOURCE" && gitleaks dir --redact --no-banner . && gitleaks git --redact --no-banner)
    git -C "$DOTFILES_SOURCE" add -- .
    git -C "$DOTFILES_SOURCE" -c user.name=phcorp -c user.email=725023+phcorp@users.noreply.github.com commit -m "$1"
    GIT_TERMINAL_PROMPT=0 git -C "$DOTFILES_SOURCE" push origin master
}
doctor() {
    _status=0
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
dotfiles sync [--non-interactive] | sync enable|disable
dotfiles publish "commit message" | doctor | recover
dotfiles mode interactive|non-interactive
EOF
}
main() {
    _action=${1:-wizard}; [ $# = 0 ] || shift
    # The explicit wizard is interactive even when first-use installs are unattended.
    [ "$_action" != wizard ] || DOTFILES_MODE=interactive
    _sub=; _arg=
    case $_action in tools|sync|mode) if [ $# -gt 0 ]; then case $1 in --*) ;; *) _sub=$1; shift ;; esac; fi ;;
        publish) _arg=${1:-}; [ $# = 0 ] || shift ;; esac
    while [ $# -gt 0 ]; do
        case $1 in
            --non-interactive) DOTFILES_MODE=non-interactive ;;
            --dry-run) DOTFILES_DRY_RUN=1 ;;
            --force) DOTFILES_FORCE=1 ;;
            --sync) DOTFILES_SYNC_ENABLE=1 ;;
            --profiles) shift; [ $# -gt 0 ] || { fail '--profiles needs a value'; return 1; }; DOTFILES_PROFILES=$1 ;;
            --help|-h) usage; return ;;
            *) if [ "$_action" = tools ] && [ -z "$_arg" ]; then _arg=$1; else fail "Unknown argument: $1"; return 1; fi ;;
        esac
        shift
    done
    [ "$_action" != wizard ] || { wizard; return; }
    case $_action in --help|-h|help) usage; return ;; esac
    valid_paths
    if [ "$DOTFILES_DRY_RUN" = 1 ]; then
        say "Dry run: $_action ${_sub:+$_sub }${_arg:-}${DOTFILES_PROFILES:+ profiles=$DOTFILES_PROFILES}; no files or packages changed."
        case $_action in install|repair|update) if command -v chezmoi >/dev/null 2>&1; then managed_paths; fi ;; esac
        return
    fi
    case $_action in
        tools) setup_state; case $_sub in list) tools_list ;; ensure) tools_ensure "$_arg" ;; install) tools_install "$_arg" ;; update) tools_update "$_arg" ;; remove) tools_remove "$_arg" ;; *) usage; return 1 ;; esac ;;
        doctor) doctor ;;
        mode) case $_sub in interactive|non-interactive) setup_state; printf '%s\n' "$_sub" > "$DOTFILES_CONFIG/mode" ;; *) fail 'Choose interactive or non-interactive'; return 1 ;; esac ;;
        install|repair|update|uninstall|recover|sync|publish)
            setup_state; lock_state
            case $_action in
                install) [ -n "$DOTFILES_PROFILES" ] || [ -f "$DOTFILES_CONFIG/tools" ] || DOTFILES_PROFILES=shell
                    printf '%s\n' "$DOTFILES_MODE" > "$DOTFILES_CONFIG/mode"
                    rotate_originals; save_selection; migrate_git; apply_files
                    if [ "${DOTFILES_TESTING:-0}" != 1 ] && [ -w "$DOTFILES_SOURCE/.git/config" ]; then
                        git -C "$DOTFILES_SOURCE" config user.name phcorp
                        git -C "$DOTFILES_SOURCE" config user.email 725023+phcorp@users.noreply.github.com
                        git -C "$DOTFILES_SOURCE" config core.hooksPath "$DOTFILES_SOURCE/scripts/git-hooks"
                    fi
                    [ "$DOTFILES_SYNC_ENABLE" = 0 ] || sync_enable
                    say 'Installed. Selected tools install on first use; use tools install to provision eagerly.' ;;
                repair) save_selection; apply_files; say 'Configuration repaired.' ;;
                update) save_selection; sync_repository ;;
                uninstall) uninstall_files ;;
                recover) recover_files ;;
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
    printf 'Dotfiles: 1 install, 2 update, 3 repair, 4 uninstall, 5 enable sync, 6 disable sync\nChoice [1]: ' > /dev/tty
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
        5) main sync enable ;; 6) main sync disable ;; *) fail 'Invalid wizard choice'; return 1 ;;
    esac
}
