# POSIX environment shared by login and interactive shells.
[ "${_DOTFILES_ENV_LOADED-}" = 1 ] && return 0
_DOTFILES_ENV_LOADED=1
: "${XDG_CONFIG_HOME:=$HOME/.config}"
: "${XDG_DATA_HOME:=$HOME/.local/share}"
: "${XDG_STATE_HOME:=$HOME/.local/state}"
: "${XDG_CACHE_HOME:=$HOME/.cache}"
export XDG_CONFIG_HOME XDG_DATA_HOME XDG_STATE_HOME XDG_CACHE_HOME
_dotfiles_prepend_path() {
    [ -d "$1" ] || return 0
    case ":$PATH:" in *":$1:"*) ;; *) PATH=$1:$PATH ;; esac
}
case $(uname -s) in
    Darwin)
        _dotfiles_prepend_path /usr/local/bin
        _dotfiles_prepend_path /opt/homebrew/bin
        _dotfiles_prepend_path /opt/homebrew/sbin
        ;;
esac
_dotfiles_prepend_path "$HOME/.local/bin"
[ ! -r "$HOME/.cargo/env" ] || . "$HOME/.cargo/env"
_dotfiles_prepend_path "$HOME/.cargo/bin"
_dotfiles_prepend_path "$HOME/.bun/bin"
export PATH
unset -f _dotfiles_prepend_path
[ ! -r "$XDG_CONFIG_HOME/dotfiles/local/env.sh" ] || . "$XDG_CONFIG_HOME/dotfiles/local/env.sh"
