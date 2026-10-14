# Shared interactive helpers. No work is done in noninteractive shells.
case $- in *i*) ;; *) return ;; esac
# Wrappers use external executable discovery (shell functions are not installs).
_dotfiles_external_exists() {
    local tool_name=$1 remaining_path=${PATH-} search_dir
    while :; do
        case $remaining_path in
            *:*) search_dir=${remaining_path%%:*}; remaining_path=${remaining_path#*:} ;;
            *) search_dir=$remaining_path; remaining_path= ;;
        esac
        [ -n "$search_dir" ] || search_dir=.
        if [ -f "$search_dir/$tool_name" ] && [ -x "$search_dir/$tool_name" ]; then
            return 0
        fi
        [ -n "$remaining_path" ] || break
    done
    return 1
}
_dotfiles_tool() {
    local tool_id=$1 tool_command=$2
    shift 2
    if ! _dotfiles_external_exists "$tool_command"; then
        command dotfiles tools ensure "$tool_id" || return $?
        hash -r 2>/dev/null || true
    fi
    command "$tool_command" "$@"
}
ls() {
    if _dotfiles_external_exists eza; then
        command eza "$@"
    elif _dotfiles_external_exists dotfiles && command dotfiles tools ensure eza; then
        command eza "$@"
    else
        command ls "$@"
    fi
}
sc() {
    local console_path
    if [ -f bin/console ]; then
        console_path=bin/console
    elif [ -f app/console ]; then
        console_path=app/console
    else
        printf '%s\n' 'sc: no bin/console or app/console in the current directory' >&2
        return 1
    fi
    php "$console_path" "$@"
}
tsplit() { tmux split-window "$@"; }
ssh-use-key() {
    [ "$#" -eq 1 ] || { printf '%s\n' 'usage: ssh-use-key PATH' >&2; return 2; }
    case $(uname -s) in
        Darwin) command ssh-add --apple-use-keychain "$1" ;;
        *) command ssh-add "$1" ;;
    esac
}
alias ll='ls -alF'
alias la='ls -A'
alias l='ls -CF'
# Preserve existing runtime managers; never install or select runtime versions here.
export NVM_DIR=${NVM_DIR:-"$HOME/.nvm"}
[ ! -s "$NVM_DIR/nvm.sh" ] || . "$NVM_DIR/nvm.sh"
if _dotfiles_external_exists pyenv; then
    eval "$(command pyenv init -)"
fi
if [ "${DOTFILES_INIT_RVM:-1}" = 1 ] && [ -s "$HOME/.rvm/scripts/rvm" ]; then
    . "$HOME/.rvm/scripts/rvm"
fi

starship() { _dotfiles_tool starship starship "$@"; }
eza() { _dotfiles_tool eza eza "$@"; }
bat() { _dotfiles_tool bat bat "$@"; }
rg() { _dotfiles_tool ripgrep rg "$@"; }
fd() { _dotfiles_tool fd fd "$@"; }
fzf() { _dotfiles_tool fzf fzf "$@"; }
jq() { _dotfiles_tool jq jq "$@"; }
zoxide() { _dotfiles_tool zoxide zoxide "$@"; }
tmux() { _dotfiles_tool tmux tmux "$@"; }
gh() { _dotfiles_tool gh gh "$@"; }
glab() { _dotfiles_tool glab glab "$@"; }
task() { _dotfiles_tool task task "$@"; }
git-lfs() { _dotfiles_tool git-lfs git-lfs "$@"; }
tree() { _dotfiles_tool tree tree "$@"; }
shellcheck() { _dotfiles_tool shellcheck shellcheck "$@"; }
hyperfine() { _dotfiles_tool hyperfine hyperfine "$@"; }
node() { _dotfiles_tool node node "$@"; }
python3() { _dotfiles_tool python python3 "$@"; }
ruby() { _dotfiles_tool ruby ruby "$@"; }
go() { _dotfiles_tool go go "$@"; }
rustc() { _dotfiles_tool rust rustc "$@"; }
cargo() { _dotfiles_tool rust cargo "$@"; }
bun() { _dotfiles_tool bun bun "$@"; }
php() { _dotfiles_tool php php "$@"; }
composer() { _dotfiles_tool composer composer "$@"; }
symfony() { _dotfiles_tool symfony symfony "$@"; }
deno() { _dotfiles_tool deno deno "$@"; }
docker() { _dotfiles_tool docker docker "$@"; }
kubectl() { _dotfiles_tool kubectl kubectl "$@"; }
helm() { _dotfiles_tool helm helm "$@"; }
terraform() { _dotfiles_tool terraform terraform "$@"; }
psql() { _dotfiles_tool psql psql "$@"; }
mysql() { _dotfiles_tool mysql mysql "$@"; }
redis-cli() { _dotfiles_tool redis redis-cli "$@"; }
code() { _dotfiles_tool code code "$@"; }
jetbrains-toolbox() { _dotfiles_tool jetbrains-toolbox jetbrains-toolbox "$@"; }
firefox() { _dotfiles_tool firefox firefox "$@"; }
google-chrome() { _dotfiles_tool chrome google-chrome "$@"; }
pgadmin4() { _dotfiles_tool pgadmin pgadmin4 "$@"; }
orb() { _dotfiles_tool orbstack orb "$@"; }
utmctl() { _dotfiles_tool utm utmctl "$@"; }
