# Use the completion integration provided by an existing package manager.
for _dotfiles_completion in /opt/homebrew/etc/profile.d/bash_completion.sh /usr/local/etc/profile.d/bash_completion.sh /etc/bash_completion /usr/share/bash-completion/bash_completion; do
    if [ -r "$_dotfiles_completion" ]; then
        . "$_dotfiles_completion"
        break
    fi
done
unset _dotfiles_completion
HISTCONTROL=ignoreboth
HISTSIZE=10000
HISTFILESIZE=20000
shopt -s histappend checkwinsize
# Keep default history in ~/.bash_history for migration compatibility.
if [ -n "${TERM-}" ] && [ "$TERM" != dumb ] && _dotfiles_external_exists starship; then
    eval "$(command starship init bash)"
else
    PS1='\u@\h:\w\$ '
fi
if _dotfiles_external_exists zoxide; then
    eval "$(command zoxide init bash)"
fi
[ ! -r "$XDG_CONFIG_HOME/dotfiles/local/bash.sh" ] || . "$XDG_CONFIG_HOME/dotfiles/local/bash.sh"
