HISTFILE=${HISTFILE:-$HOME/.zsh_history}
HISTSIZE=10000
SAVEHIST=20000
setopt APPEND_HISTORY HIST_IGNORE_DUPS HIST_IGNORE_SPACE
# Ignore insecure completion directories without prompting during startup.
autoload -Uz compinit
compinit -i
if [ -n "${TERM-}" ] && [ "$TERM" != dumb ] && _dotfiles_external_exists starship; then
    eval "$(command starship init zsh)"
else
    PROMPT='%n@%m:%~%# '
fi
if _dotfiles_external_exists zoxide; then
    eval "$(command zoxide init zsh)"
fi
[ ! -r "$XDG_CONFIG_HOME/dotfiles/local/zsh.sh" ] || . "$XDG_CONFIG_HOME/dotfiles/local/zsh.sh"
