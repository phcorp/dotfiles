# Portable private lock ownership. Definition-only; callers own signal/exit traps.
# API: lock_acquire PATH; lock_status PATH; lock_release PATH; lock_recover_stale PATH.
# Successful acquisition remembers LOCK_NONCE/_lock_nonce and _lock_path in this shell.
_lock_error() { printf 'dotfiles: %s\n' "$*" >&2; return 1; }
_lock_parent_safe() (
    case $1 in /*) ;; *) _lock_error 'Lock path must be absolute.'; return 1 ;; esac
    case $1 in *'/../'*|*'/..'|*'/./'*|*'/.'|*"$(printf '\t')"*|*'
'*) _lock_error 'Unsafe lock path.'; return 1 ;; esac
    [ ! -L "$1" ] || { _lock_error 'Lock cannot be a symlink.'; return 1; }
    _lp_parent=$(dirname "$1")
    while [ ! -d "$_lp_parent" ]; do
        [ ! -L "$_lp_parent" ] || { _lock_error 'Broken symlink in lock parent.'; return 1; }
        [ "$_lp_parent" != / ] || return 1
        _lp_parent=$(dirname "$_lp_parent")
    done
    _lp_actual=$(CDPATH='' cd "$_lp_parent" && pwd -P) || return
    _lp_home=$(CDPATH='' cd "$HOME" && pwd -P) || return
    [ "$_lp_home" != / ] || return 1
    case "$_lp_actual/" in "$_lp_home/"*) ;; *) _lock_error 'Lock parent escapes HOME.'; return 1 ;; esac
)
_lock_host() { LC_ALL=C hostname 2>/dev/null; }
_lock_start() { TZ=UTC LC_ALL=C ps -p "$1" -o lstart= 2>/dev/null | awk '{$1=$1; print}'; }
_lock_metadata() {
    [ -d "$1" ] && [ ! -L "$1" ] && [ -f "$1/owner" ] && [ ! -L "$1/owner" ] || return 1
    awk -F '\t' 'NR!=1 || NF!=6 {bad=1} END {exit bad || NR!=1}' "$1/owner" || return
    IFS="$(printf '\t')" read -r _lock_owner_version _lock_owner_pid _lock_owner_host _lock_owner_start _lock_owner_created _lock_owner_nonce < "$1/owner" || return
    [ "$_lock_owner_version" = 1 ] || return 1
    case $_lock_owner_pid in ''|0|*[!0-9]*) return 1 ;; esac
    case $_lock_owner_created in ''|*[!0-9]*) return 1 ;; esac
    case $_lock_owner_host in ''|*[!A-Za-z0-9_.-]*) return 1 ;; esac
    case $_lock_owner_nonce in ''|*[!A-Za-z0-9_.-]*) return 1 ;; esac
    case $_lock_owner_start in ''|*[!A-Za-z0-9:\ /-]*) return 1 ;; esac
}
_lock_classify() {
    _lock_result=unknown
    if [ ! -e "$1" ] && [ ! -L "$1" ]; then _lock_result=absent; return; fi
    _lock_metadata "$1" || return 0
    _lock_current_host=$(_lock_host) || return 0
    [ "$_lock_current_host" = "$_lock_owner_host" ] || return 0
    _lock_current_start=$(_lock_start "$_lock_owner_pid")
    if [ -n "$_lock_current_start" ]; then
        if [ "$_lock_current_start" = "$_lock_owner_start" ]; then _lock_result=active
        else _lock_result=stale; fi
        return
    fi
    # ps can hide a process or fail. Only a definite missing PID proves staleness.
    _lock_kill_status=0
    _lock_kill_message=$(LC_ALL=C kill -0 "$_lock_owner_pid" 2>&1) || _lock_kill_status=$?
    if [ "$_lock_kill_status" != 0 ]; then
        case $_lock_kill_message in *'No such process'*) _lock_result=stale ;; esac
    fi
    return 0
}
lock_status() (
    _lock_parent_safe "$1" >/dev/null 2>&1 || { printf 'unknown\n'; return; }
    _lock_classify "$1"
    printf '%s\n' "$_lock_result"
)
lock_acquire() {
    _lock_parent_safe "$1" || return
    _lock_acquire_host=$(_lock_host) || return
    _lock_acquire_start=$(_lock_start "$$")
    [ -n "$_lock_acquire_start" ] || { _lock_error 'Cannot determine lock owner process identity.'; return 1; }
    case $_lock_acquire_host in ''|*[!A-Za-z0-9_.-]*) _lock_error 'Cannot determine lock owner host identity.'; return 1 ;; esac
    mkdir -m 700 "$1" 2>/dev/null || { _lock_error "Lock is $(lock_status "$1"); use explicit stale recovery when appropriate."; return 1; }
    _lock_acquire_temp=$(mktemp "$1/owner.XXXXXX") || { rmdir "$1" 2>/dev/null || :; return 1; }
    LOCK_NONCE=$(basename "$_lock_acquire_temp")
    _lock_nonce=$LOCK_NONCE
    _lock_path=$1
    if ! printf '1\t%s\t%s\t%s\t%s\t%s\n' "$$" "$_lock_acquire_host" "$_lock_acquire_start" "$(date -u +%s)" "$LOCK_NONCE" > "$_lock_acquire_temp" ||
       ! chmod 600 "$_lock_acquire_temp" || ! mv "$_lock_acquire_temp" "$1/owner"; then
        rm -f "$_lock_acquire_temp"
        rmdir "$1" 2>/dev/null || :
        return 1
    fi
}
lock_release() (
    _lock_parent_safe "$1" || return
    [ -e "$1" ] || return 0
    _lock_metadata "$1" || { _lock_error 'Lock ownership cannot be verified for release.'; return 1; }
    if [ "${_lock_path:-}" != "$1" ] || [ -z "${LOCK_NONCE:-${_lock_nonce:-}}" ] ||
        [ "$_lock_owner_nonce" != "${LOCK_NONCE:-${_lock_nonce:-}}" ] || [ "$_lock_owner_pid" != "$$" ]; then
        _lock_error 'Lock ownership changed; release refused.'; return 1;
    fi
    [ "$_lock_owner_host" = "$(_lock_host)" ] && [ "$_lock_owner_start" = "$(_lock_start "$$")" ] || return 1
    [ ! -e "$1/reclaim" ] || { _lock_error 'Lock reclaim in progress; release refused.'; return 1; }
    # Refuse unexpected contents rather than deleting files in an unrecognized lock.
    _lock_entries=$(find "$1" -mindepth 1 -maxdepth 1 -print | wc -l | tr -d ' ')
    [ "$_lock_entries" = 1 ] || { _lock_error 'Unexpected lock contents; release refused.'; return 1; }
    rm -f "$1/owner" && rmdir "$1"
)
_lock_cleanup_claim() {
    [ -n "${_lock_reclaim_original:-}" ] || return 0
    if _lock_metadata "$_lock_reclaim_original" && [ "$_lock_owner_nonce" = "$_lock_expected_nonce" ]; then
        rmdir "$_lock_reclaim_original/reclaim" 2>/dev/null || :
    fi
}
lock_recover_stale() (
    _lock_parent_safe "$1" || return
    _lock_classify "$1"
    [ "$_lock_result" = stale ] || { _lock_error "Lock is $_lock_result; stale recovery refused."; return 1; }
    _lock_expected_nonce=$_lock_owner_nonce
    _lock_expected_owner=$(cat "$1/owner") || return
    mkdir -m 700 "$1/reclaim" 2>/dev/null || { _lock_error 'Another stale recovery is in progress.'; return 1; }
    _lock_reclaim_original=$1
    trap '_lock_cleanup_claim' EXIT
    _lock_classify "$1"
    if [ "$_lock_result" != stale ] || [ "$_lock_owner_nonce" != "$_lock_expected_nonce" ] ||
        [ "$(cat "$1/owner")" != "$_lock_expected_owner" ]; then _lock_error 'Lock ownership changed during recovery.'; return 1; fi
    _lock_entries=$(find "$1" -mindepth 1 -maxdepth 1 -print | wc -l | tr -d ' ')
    [ "$_lock_entries" = 2 ] || { _lock_error 'Unexpected lock contents; stale recovery refused.'; return 1; }
    _lock_quarantine=$(mktemp -d "$(dirname "$1")/.lock-recovered.XXXXXX") || return
    # The original pathname becomes free only after its complete stale owner is moved.
    if ! mv "$1" "$_lock_quarantine/lock"; then rmdir "$_lock_quarantine"; return 1; fi
    _lock_reclaim_original=
    rm -f "$_lock_quarantine/lock/owner" && rmdir "$_lock_quarantine/lock/reclaim" &&
        rmdir "$_lock_quarantine/lock" && rmdir "$_lock_quarantine"
)
