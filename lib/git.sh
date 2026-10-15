# Private Git setup uses the lifecycle lock and recovery journal.
git_setup_cleanup() {
    if [ -n "${_git_stage:-}" ]; then rm -rf "$_git_stage"; fi
}
git_setup() (
    _git_stage=$(mktemp -d) || return
    trap 'git_setup_cleanup' EXIT
    trap 'exit 129' HUP
    trap 'exit 130' INT
    trap 'exit 143' TERM
    _git_mode=interactive
    if [ "$DOTFILES_DRY_RUN" = 1 ]; then _git_mode=preview
    elif [ "$DOTFILES_MODE" = non-interactive ]; then _git_mode=non-interactive; fi
    python3 "$DOTFILES_SOURCE/scripts/git-setup.py" prepare "$_git_stage" "$_git_mode" || return
    [ "$DOTFILES_DRY_RUN" = 0 ] || return 0
    setup_state || return
    lock_state || return
    begin_transaction || return
    if ! python3 "$DOTFILES_SOURCE/scripts/git-setup.py" apply "$_git_stage"; then
        recover_files || return
        return 1
    fi
    commit_transaction
)
