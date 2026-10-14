# Private, literal configuration. Never source the settings data file.
# settings_load; settings_check_origin [SOURCE]; settings_publish_git_env.
_settings_error() { printf '%s\n' "$1" >&2; return 1; }
_settings_repository_slug() {
    case $1 in
        https://github.com/*) _settings_slug=${1#https://github.com/} ;;
        git@github.com:*) _settings_slug=${1#git@github.com:} ;;
        *) _settings_error 'Repository must be a credential-free GitHub HTTPS or SSH URL.'; return 1 ;;
    esac
    _settings_slug=${_settings_slug%.git}
    case $_settings_slug in */.|*/..) _settings_error 'Invalid configured repository.'; return 1 ;; esac
    printf '%s\n' "$_settings_slug" | LC_ALL=C grep -Eq '^[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_.-]+$' || {
        _settings_error 'Invalid configured repository.'; return 1;
    }
    printf '%s\n' "$_settings_slug" | tr '[:upper:]' '[:lower:]'
}
_settings_validate() {
    _settings_repository_slug "$1" >/dev/null || return
    _settings_checked_branch=$(git check-ref-format --branch "$2" 2>/dev/null) || { _settings_error 'Invalid configured branch.'; return 1; }
    [ "$_settings_checked_branch" = "$2" ] || { _settings_error 'Branch must be a literal Git branch name.'; return 1; }
    case $4 in *@users.noreply.github.com) _settings_alias=${4%@users.noreply.github.com} ;; *) _settings_error 'Publication requires a matching GitHub noreply identity.'; return 1 ;; esac
    case $_settings_alias in
        *+*) _settings_numeric=${_settings_alias%%+*}; _settings_alias=${_settings_alias#*+}
            case $_settings_numeric in ''|*[!0-9]*) _settings_error 'Invalid publication noreply identity.'; return 1 ;; esac ;;
    esac
    printf '%s\n' "$_settings_alias" | LC_ALL=C grep -Eq '^[A-Za-z0-9_.-]+(\[bot\])?$' && [ "$3" = "$_settings_alias" ] || {
        _settings_error 'Publication name must match its GitHub noreply alias.'; return 1;
    }
}
_settings_file_safe() (
    _settings_file=$1
    case $_settings_file in /*) ;; *) _settings_error 'Private settings require an absolute configuration path.'; return 1 ;; esac
    [ ! -L "$_settings_file" ] || { _settings_error 'Private settings cannot be a symlink.'; return 1; }
    [ -e "$_settings_file" ] || return 0
    [ -f "$_settings_file" ] || { _settings_error 'Private settings must be a regular file.'; return 1; }
    _settings_physical=$(CDPATH='' cd "$(dirname "$_settings_file")" && pwd -P) || return
    _settings_home=$(CDPATH='' cd "$HOME" && pwd -P) || return
    case "$_settings_physical/" in "$_settings_home/"*) ;; *) _settings_error 'Private settings directory escapes HOME.'; return 1 ;; esac
    case $(uname -s) in
        Darwin) _settings_mode=$(stat -f '%Lp' "$_settings_file"); _settings_owner=$(stat -f '%u' "$_settings_file") ;;
        Linux) _settings_mode=$(stat -c '%a' "$_settings_file"); _settings_owner=$(stat -c '%u' "$_settings_file") ;;
        *) _settings_error 'Cannot validate private settings permissions on this OS.'; return 1 ;;
    esac
    case $_settings_mode in 400|600) ;; *) _settings_error 'Private settings require owner-only permissions (chmod 600).' ; return 1 ;; esac
    [ "$_settings_owner" = "$(id -u)" ] || { _settings_error 'Private settings must belong to the current user.'; return 1; }
)
settings_load() {
    _settings_file=${DOTFILES_CONFIG:-${XDG_CONFIG_HOME:-$HOME/.config}/dotfiles}/settings
    _settings_file_safe "$_settings_file" || return
    _settings_repository=https://github.com/phcorp/dotfiles.git
    _settings_branch=master
    _settings_name=phcorp
    _settings_email=725023+phcorp@users.noreply.github.com
    _settings_seen_repository=0; _settings_seen_branch=0; _settings_seen_name=0; _settings_seen_email=0
    if [ -f "$_settings_file" ]; then
        while IFS= read -r _settings_line || [ -n "$_settings_line" ]; do
            case $_settings_line in ''|'#'*) continue ;; esac
            case $_settings_line in *=*) ;; *) _settings_error 'Private settings require literal KEY=value lines.'; return 1 ;; esac
            _settings_key=${_settings_line%%=*}; _settings_value=${_settings_line#*=}
            case $_settings_key in
                DOTFILES_REPOSITORY)
                    [ "$_settings_seen_repository" = 0 ] || { _settings_error 'Duplicate private settings key.'; return 1; }
                    _settings_seen_repository=1; _settings_repository=$_settings_value ;;
                DOTFILES_BRANCH)
                    [ "$_settings_seen_branch" = 0 ] || { _settings_error 'Duplicate private settings key.'; return 1; }
                    _settings_seen_branch=1; _settings_branch=$_settings_value ;;
                DOTFILES_PUBLISH_NAME)
                    [ "$_settings_seen_name" = 0 ] || { _settings_error 'Duplicate private settings key.'; return 1; }
                    _settings_seen_name=1; _settings_name=$_settings_value ;;
                DOTFILES_PUBLISH_EMAIL)
                    [ "$_settings_seen_email" = 0 ] || { _settings_error 'Duplicate private settings key.'; return 1; }
                    _settings_seen_email=1; _settings_email=$_settings_value ;;
                *) _settings_error 'Unknown private settings key.'; return 1 ;;
            esac
        done < "$_settings_file"
    fi
    # The + expansion distinguishes an explicitly empty environment value from unset.
    if [ "${DOTFILES_REPOSITORY+x}" = x ]; then _settings_repository=$DOTFILES_REPOSITORY; fi
    if [ "${DOTFILES_BRANCH+x}" = x ]; then _settings_branch=$DOTFILES_BRANCH; fi
    if [ "${DOTFILES_PUBLISH_NAME+x}" = x ]; then _settings_name=$DOTFILES_PUBLISH_NAME; fi
    if [ "${DOTFILES_PUBLISH_EMAIL+x}" = x ]; then _settings_email=$DOTFILES_PUBLISH_EMAIL; fi
    _settings_validate "$_settings_repository" "$_settings_branch" "$_settings_name" "$_settings_email" || return
    DOTFILES_REPOSITORY=$_settings_repository
    DOTFILES_BRANCH=$_settings_branch
    DOTFILES_PUBLISH_NAME=$_settings_name
    DOTFILES_PUBLISH_EMAIL=$_settings_email
    export DOTFILES_REPOSITORY DOTFILES_BRANCH DOTFILES_PUBLISH_NAME DOTFILES_PUBLISH_EMAIL
}
_settings_check_urls() {
    printf '%s\n' "$1" | while IFS= read -r _settings_url; do
        if [ "${DOTFILES_TESTING:-0}" = 1 ] && [ "${DOTFILES_SYNC_SKIP_CI:-0}" = 1 ]; then
            case $_settings_url in /*|./*|../*|file://*) continue ;; esac
        fi
        _settings_actual=$(_settings_repository_slug "$_settings_url") || exit 1
        [ "$_settings_actual" = "$_settings_expected" ] || { _settings_error 'Origin differs from the configured repository; refusing fetch or push.'; exit 1; }
    done
}
settings_check_origin() (
    _settings_source=${1:-${DOTFILES_SOURCE:-}}
    [ -n "$_settings_source" ] || { _settings_error 'A source checkout is required.'; return 1; }
    _settings_expected=$(_settings_repository_slug "${DOTFILES_REPOSITORY-https://github.com/phcorp/dotfiles.git}") || return
    _settings_fetch=$(git -C "$_settings_source" remote get-url --all origin 2>/dev/null) || { _settings_error 'Source checkout has no usable origin.'; return 1; }
    _settings_push=$(git -C "$_settings_source" remote get-url --push --all origin 2>/dev/null) || { _settings_error 'Source checkout has no usable push origin.'; return 1; }
    [ -n "$_settings_fetch" ] && [ -n "$_settings_push" ] || { _settings_error 'Origin URLs must not be empty.'; return 1; }
    _settings_check_urls "$_settings_fetch" && _settings_check_urls "$_settings_push"
)
settings_publish_git_env() {
    _settings_validate "${DOTFILES_REPOSITORY-https://github.com/phcorp/dotfiles.git}" "${DOTFILES_BRANCH-master}" "${DOTFILES_PUBLISH_NAME-phcorp}" "${DOTFILES_PUBLISH_EMAIL-725023+phcorp@users.noreply.github.com}" || return
    GIT_AUTHOR_NAME=${DOTFILES_PUBLISH_NAME-phcorp}
    GIT_COMMITTER_NAME=$GIT_AUTHOR_NAME
    GIT_AUTHOR_EMAIL=${DOTFILES_PUBLISH_EMAIL-725023+phcorp@users.noreply.github.com}
    GIT_COMMITTER_EMAIL=$GIT_AUTHOR_EMAIL
    export GIT_AUTHOR_NAME GIT_COMMITTER_NAME GIT_AUTHOR_EMAIL GIT_COMMITTER_EMAIL
}
