#!/usr/bin/env python3
"""Preserve reviewed categories of existing shell integrations locally, never in Git."""
import argparse
import os
import pathlib
import re

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--home', type=pathlib.Path, default=pathlib.Path.home())
args = parser.parse_args()
home = args.home.resolve()
config = pathlib.Path(os.environ.get('XDG_CONFIG_HOME', str(home / '.config')))
local = config / 'dotfiles/local'
if not local.resolve().is_relative_to(home):
    raise SystemExit('Private overrides must remain within HOME.')
for directory in (config, config / 'dotfiles', local):
    if directory.is_symlink():
        raise SystemExit('Refusing symlinked private override directories.')
local.mkdir(parents=True, exist_ok=True, mode=0o700)
local.chmod(0o700)

def write(name, lines):
    target = local / name
    if target.exists() or target.is_symlink() or not lines:
        return
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w') as output:
        output.write('# Machine-local integrations migrated from previous configuration.\n')
        output.write('\n'.join(lines) + '\n')

environment = []
hooks = {}
editor = []
uses_project_node = False
rvm_shells = set()
excluded = {'ZSH', 'ZSH_THEME', 'DISABLE_UPDATE_PROMPT', 'TERM', 'LANG', 'LC_COLLATE', 'NVM_DIR', 'BUN_INSTALL', 'EDITOR'}
for filename in ('.profile', '.bash_profile', '.zprofile', '.bashrc', '.zshrc'):
    path = home / filename
    if not path.is_file():
        continue
    shell = 'zsh' if filename.startswith('.z') else 'bash'
    login = filename.endswith('profile')
    extras, pre = [], []
    source = path.read_text()
    if '.rvm/scripts/rvm' in source:
        rvm_shells.add(shell)
    uses_project_node = uses_project_node or '.nvmrc' in source
    editor_block = re.search(r'if \[\[ -n \$SSH_CONNECTION \]\]; then\s*\n(.*?)\nelse\s*\n(.*?)\nfi', source, re.S)
    if editor_block and not editor:
        editor = ['if [ -n "${SSH_CONNECTION-}" ]; then', editor_block[1], 'else', editor_block[2], 'fi']
    for line in source.splitlines():
        stripped = line.strip()
        match = re.match(r'export\s+([A-Za-z_][A-Za-z_0-9]*)=', stripped)
        if match and match[1] not in excluded:
            # Retain literal machine settings; regenerate manager init through managed hooks.
            if '$(' not in stripped and '`' not in stripped and '$PWD' not in stripped:
                if match[1] != 'PATH' or not re.search(r'(^|[=:])\.?\.?/(?:bin|node_modules|vendor)', stripped):
                    environment.append(stripped)
            continue
        if 'kiro-cli/shell/' in stripped:
            (pre if '.pre.' in stripped else extras).append(stripped)
        elif 'kiro --locate-shell-integration-path' in stripped:
            extras.append(stripped.split('# Added')[0])
        elif '.orbstack/shell/init.' in stripped or 'google-cloud-sdk/' in stripped:
            extras.append(stripped)
        elif stripped.startswith('alias ') and not re.search(r'\b(?:dotenv|updatedb|pulsesecure-reset|ls|la|ll|lt|ltt|lttt|ltttt)=', stripped):
            extras.append(stripped)
    prefix = 'pre-login-' if login else 'pre-'
    suffix = 'login-' if login else ''
    hooks.setdefault(prefix + shell + '.sh', []).extend(pre)
    hooks.setdefault(suffix + shell + '.sh', []).extend(extras)
for name, lines in hooks.items():
    write(name, list(dict.fromkeys(lines)))
environment = list(dict.fromkeys(environment)) + editor
environment += [
    'if [ -n "${ZSH_VERSION-}" ]; then',
    '    DOTFILES_INIT_RVM=' + str(int('zsh' in rvm_shells)),
    'else',
    '    DOTFILES_INIT_RVM=' + str(int('bash' in rvm_shells)),
    'fi',
]
# Deduplicate PATH entries even when several former startup files set them.
environment += [
    '_dotfiles_remaining=$PATH; PATH=',
    'while :; do',
    '    case $_dotfiles_remaining in *:*) _dotfiles_entry=${_dotfiles_remaining%%:*}; _dotfiles_remaining=${_dotfiles_remaining#*:} ;; *) _dotfiles_entry=$_dotfiles_remaining; _dotfiles_remaining= ;; esac',
    '    if [ -n "$_dotfiles_entry" ]; then case ":$PATH:" in *":$_dotfiles_entry:"*) ;; *) PATH=${PATH:+$PATH:}$_dotfiles_entry ;; esac; fi',
    '    [ -n "$_dotfiles_remaining" ] || break',
    'done',
    'export PATH; unset _dotfiles_remaining _dotfiles_entry',
]
write('env.sh', environment)
if uses_project_node:
    # Preserve the prior opt-in project Node switching without importing eval helpers.
    project_node = [
        '_dotfiles_project_node() {',
        '    command -v nvm >/dev/null 2>&1 || return 0',
        '    local directory=$PWD',
        '    while [ "$directory" != / ] && [ ! -f "$directory/.nvmrc" ]; do directory=${directory%/*}; [ -n "$directory" ] || directory=/; done',
        '    [ -f "$directory/.nvmrc" ] || return 0',
        '    local desired; desired=$(nvm version "$(cat "$directory/.nvmrc")")',
        '    [ "$desired" != N/A ] || return 0',
        '    [ "$(nvm current)" = "$desired" ] || nvm use --silent "$desired" >/dev/null',
        '}',
    ]
    for shell in ('bash', 'zsh'):
        target = local / (shell + '.sh')
        if target.is_symlink():
            raise SystemExit('Refusing symlinked private shell overrides.')
        marker = '_dotfiles_project_node()'
        if target.exists() and marker in target.read_text():
            continue
        additions = project_node + ([
            'case ${PROMPT_COMMAND-} in *_dotfiles_project_node*) ;; *) PROMPT_COMMAND="_dotfiles_project_node${PROMPT_COMMAND:+;$PROMPT_COMMAND}" ;; esac'
        ] if shell == 'bash' else [
            'autoload -Uz add-zsh-hook',
            'add-zsh-hook precmd _dotfiles_project_node'
        ])
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, 'w') as output:
            output.write('\n' + '\n'.join(additions) + '\n')
print('Private shell integrations preserved locally. Existing override files were retained.')
