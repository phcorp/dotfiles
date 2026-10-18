HISTFILE=${HISTFILE:-$HOME/.zsh_history}
HISTSIZE=10000
SAVEHIST=20000
setopt APPEND_HISTORY HIST_IGNORE_DUPS HIST_IGNORE_SPACE
# Package-manager completions must be visible before compinit builds its cache.
for _dotfiles_completion_dir in /opt/homebrew/share/zsh/site-functions /usr/local/share/zsh/site-functions; do
    if [[ -d $_dotfiles_completion_dir && ${fpath[(Ie)$_dotfiles_completion_dir]} == 0 ]]; then
        fpath=("$_dotfiles_completion_dir" $fpath)
    fi
done
unset _dotfiles_completion_dir
zstyle ':completion:*' completer _complete _match
zstyle ':completion:*' matcher-list '' 'm:{a-zA-Z}={A-Za-z}' 'r:|[._-]=* r:|=*'
zstyle ':completion:*:descriptions' format '[%d]'
zstyle ':completion:*' group-name ''
zstyle ':completion:*' menu select
zmodload zsh/complist
# Ignore insecure completion directories without prompting during startup.
autoload -Uz compinit
compinit -i
# Keep multiline editing, then search the complete prefix before the cursor.
autoload -Uz up-line-or-beginning-search down-line-or-beginning-search
zle -N up-line-or-beginning-search
zle -N down-line-or-beginning-search
for _dotfiles_keymap in emacs viins; do
    bindkey -M "$_dotfiles_keymap" '^[[A' up-line-or-beginning-search
    bindkey -M "$_dotfiles_keymap" '^[OA' up-line-or-beginning-search
    bindkey -M "$_dotfiles_keymap" '^[[B' down-line-or-beginning-search
    bindkey -M "$_dotfiles_keymap" '^[OB' down-line-or-beginning-search
done
unset _dotfiles_keymap
# Use only an already-installed executable; never install tools during startup.
if _dotfiles_external_exists fzf && [[ -r $XDG_CONFIG_HOME/dotfiles/vendor/fzf-tab/fzf-tab.plugin.zsh ]]; then
    zstyle ':completion:*' menu no
    source "$XDG_CONFIG_HOME/dotfiles/vendor/fzf-tab/fzf-tab.plugin.zsh"
fi
if [ -n "${TERM-}" ] && [ "$TERM" != dumb ] && _dotfiles_external_exists starship; then
    eval "$(command starship init zsh)"
else
    PROMPT='%n@%m:%~%# '
fi
if _dotfiles_external_exists zoxide; then
    eval "$(command zoxide init zsh)"
fi
[ ! -r "$XDG_CONFIG_HOME/dotfiles/local/zsh.sh" ] || . "$XDG_CONFIG_HOME/dotfiles/local/zsh.sh"
