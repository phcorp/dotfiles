# Read-only lifecycle previews; never call alias/install/scheduler mutations here.
# shellcheck disable=SC2154
preview_tool() (
    _tools_id=$1; _preview_operation=$2
    _tools_record=$(_tools_row "$_tools_id") || { fail 'Unknown tool in preview.'; return 1; }
    _tools_paths_safe || return
    _preview_present=0
    _tools_available "$_tools_record" && _preview_present=1
    if [ "$(uname -s)" = Darwin ]; then
        case $(_tools_field "$_tools_record" 3) in
            cask:*) if _tools_alias_probe=1 _tools_alias "$_tools_id"; then _preview_present=1; fi ;;
            mas:*) desktop_exists "$_tools_id" && _preview_present=1 ;;
        esac
    fi
    if [ "$_preview_operation" = install ] && [ "$_preview_present" = 1 ]; then
        printf 'UNCHANGED tool %s: already available; existing installation preserved.\n' "$_tools_id"
        return 0
    fi
    if ! _tools_manager >/dev/null 2>&1; then
        printf 'NEEDS INFO tool %s: no supported installer for this OS, distribution, or architecture.\n' "$_tools_id"
        return 1
    fi
    _preview_manager=$_tools_manager_name; _preview_package=$_tools_package
    _preview_owned=$(awk -F '\t' -v id="$_tools_id" '$1==id && $4=="created-by-dotfiles" {print; exit}' "$DOTFILES_STATE/packages" 2>/dev/null || :)
    if [ "$_preview_operation" != install ]; then
        if [ -n "$_preview_owned" ]; then
            _tools_manager_name=$(_tools_field "$_preview_owned" 2)
            _tools_package=$(_tools_field "$_preview_owned" 3)
            case $_tools_manager_name in brew|apt|dnf|flatpak|desktop|upstream) ;; *) fail 'Invalid package ownership metadata.'; return 1 ;; esac
        elif [ "$_preview_operation" = update ] && [ "$_tools_manager_name" != upstream ] && _tools_package_exists; then
            if [ "$_tools_manager_name" = flatpak ] && [ "$_tools_flatpak_scope_value" != --user ]; then
                printf 'BLOCKED update %s: existing system Flatpak requires its administrator.\n' "$_tools_id"; return 1
            fi
        else
            printf 'BLOCKED %s %s: unowned or absent in this backend; use the original installer.\n' "$_preview_operation" "$_tools_id"; return 1
        fi
    fi
    if [ "$_preview_operation" = remove ]; then
        case $_tools_id in node|python|ruby|go|rust|bun|deno) printf 'BLOCKED remove %s: runtime removal requires its original manager.\n' "$_tools_id"; return 1 ;; esac
        if ! _tools_removal_safe >/dev/null 2>&1; then
            printf 'BLOCKED remove %s: dependency inspection failed or installed software depends on it.\n' "$_tools_id"; return 1
        fi
    fi
    # Print only catalog values, never arbitrary values from the private ledger.
    if [ "$_tools_manager_name" = "$_preview_manager" ] && [ "$_tools_package" = "$_preview_package" ]; then
        printf 'PLAN %s tool %s via %s (%s).\n' "$_preview_operation" "$_tools_id" "$_preview_manager" "$_preview_package"
    else
        printf 'PLAN %s tool %s via recorded ownership backend; differing private package details withheld.\n' "$_preview_operation" "$_tools_id"
    fi
    case $_preview_operation in
        install|update)
            case $_tools_manager_name in
                upstream|desktop) printf 'NEEDS INFO %s: pinned artifact integrity, runtime prerequisites, and authentication are checked during application.\n' "$_tools_id" ;;
                *) printf 'NEEDS INFO %s: final version, download size, and dependency changes require package-manager metadata at execution.\n' "$_tools_id" ;;
            esac ;;
    esac
    if [ "$_tools_id" = mutekey ] && [ "$(uname -s)" = Darwin ] && [ "$_preview_operation" != remove ] && [ "$DOTFILES_MODE" = non-interactive ]; then
        printf '%s\n' 'BLOCKED MuteKey installation/update requires interactive App Store authentication.'; return 1
    fi
)
preview_selection() (
    _preview_profiles=${DOTFILES_PROFILES:-}
    if [ -z "$_preview_profiles" ]; then
        if [ -f "$DOTFILES_CONFIG/tools" ]; then printf '%s\n' 'UNCHANGED existing tool selection retained.'; return; fi
        [ "$_action" = install ] || return 0
        _preview_profiles=shell
    fi
    for _preview_profile in $(printf '%s' "$_preview_profiles" | tr ',' ' '); do
        case $_preview_profile in shell|runtimes|php|cloud|databases|desktop) ;; *) fail 'Unknown profile in preview.'; return 1 ;; esac
        awk -F '\t' -v p="$_preview_profile" '$6==p {print $1}' "$DOTFILES_SOURCE/catalog.tsv" | while IFS= read -r _preview_id; do
            if tools_supported "$_preview_id"; then
                printf 'PLAN SELECT %s for first-use installation (not installed by configuration application).\n' "$_preview_id"
            else printf 'PLAN EXCLUDE %s: unsupported on this platform.\n' "$_preview_id"; fi
        done
    done
)
preview_apps() (
    case $_sub in list) awk -F '\t' 'NR==1 || $6=="desktop"' "$DOTFILES_SOURCE/catalog.tsv"; return ;; install|update|remove) ;; *) fail 'Unknown app operation in preview.'; return 1 ;; esac
    if [ -n "$_arg" ] && [ "$_arg" != all ]; then
        _preview_record=$(_tools_row "$_arg") || return
        [ "$(_tools_field "$_preview_record" 6)" = desktop ] || { fail 'This tool is not a desktop app.'; return 1; }
        preview_tool "$_arg" "$_sub"; return
    fi
    if [ "$_sub" = remove ]; then
        [ -f "$DOTFILES_STATE/packages" ] || { say 'UNCHANGED no owned apps to remove.'; return; }
        _preview_ids=$(awk -F '\t' 'NR==FNR {if ($6=="desktop") app[$1]=1; next} $1 in app && $4=="created-by-dotfiles" {print $1}' "$DOTFILES_SOURCE/catalog.tsv" "$DOTFILES_STATE/packages")
    else
        [ -f "$DOTFILES_CONFIG/tools" ] || { say 'NEEDS INFO select desktop apps before planning a batch.'; return 1; }
        _preview_ids=$(awk -F '\t' 'NR==FNR {if ($6=="desktop") app[$1]=1; next} $1 in app {print $1}' "$DOTFILES_SOURCE/catalog.tsv" "$DOTFILES_CONFIG/tools")
    fi
    _preview_failed=0
    for _preview_id in $_preview_ids; do preview_tool "$_preview_id" "$_sub" || _preview_failed=1; done
    return "$_preview_failed"
)
preview() (
    say 'Dry run: planned operations only; no files, selections, ownership, packages, or schedulers changed.'
    case $_action in
        install|repair|update|uninstall|recover)
            _preview_failed=0
            if [ "$_action" = recover ] && [ "${DOTFILES_UNLOCK_STALE:-0}" = 1 ]; then
                _preview_lock=$(lock_status "$DOTFILES_STATE/lifecycle.lock")
                case $_preview_lock in
                    stale) say 'PLAN explicitly reclaim verified stale lifecycle lock.' ;;
                    absent) say 'UNCHANGED no lifecycle lock requires reclamation.' ;;
                    *) say 'BLOCKED lock is active or unverifiable; reclamation refused.'; return 1 ;;
                esac
                [ -d "$DOTFILES_STATE/transaction" ] || return 0
            fi
            python3 "$DOTFILES_SOURCE/scripts/preview.py" "$_action" || _preview_failed=1
            case $_action in install|repair|update) preview_selection || _preview_failed=1 ;; esac
            if [ "$_action" = uninstall ]; then say 'PLAN disable owned synchronization; restore managed files and retain packages/private backups.'; fi
            if [ "$DOTFILES_SYNC_ENABLE" = 1 ]; then say 'PLAN enable hourly synchronization after successful installation (scheduler availability checked at execution).'; fi
            return "$_preview_failed" ;;
        tools) case $_sub in list) tools_list ;; ensure) preview_tool "$_arg" install ;; install|update|remove) preview_tool "$_arg" "$_sub" ;; *) fail 'Unknown tool operation in preview.'; return 1 ;; esac ;;
        apps) preview_apps ;;
        sync) case $_sub in '') python3 "$DOTFILES_SOURCE/scripts/preview.py" sync ;; enable|disable) printf 'PLAN %s owned hourly synchronization; scheduler untouched.\n' "$_sub" ;; *) fail 'Unknown sync operation in preview.'; return 1 ;; esac ;;
        mode) case $_sub in interactive|non-interactive) printf 'PLAN set first-use mode to %s.\n' "$_sub" ;; *) fail 'Invalid mode in preview.'; return 1 ;; esac ;;
        publish) say 'NEEDS INFO publication requires explicit execution, validated identity, secret scans, and reviewed changes. No commit or push planned automatically.' ;;
        git) case $_sub in setup) git_setup ;; status) python3 "$DOTFILES_SOURCE/scripts/git-setup.py" status ;; *) fail 'Choose git setup or git status.'; return 1 ;; esac ;;
        doctor) doctor ;;
        *) fail 'Unknown action in preview.'; return 1 ;;
    esac
)
