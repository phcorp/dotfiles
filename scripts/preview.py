#!/usr/bin/env python3
"""Read-only, privacy-filtered configuration plans from chezmoi target state."""
import difflib
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile


HOME = Path(os.environ['HOME']).absolute()
CONFIG = Path(os.environ['XDG_CONFIG_HOME']).absolute()
STATE = Path(os.environ['DOTFILES_STATE']).absolute()
SOURCE = Path(os.environ['DOTFILES_SOURCE']).absolute()
FORCE = os.environ.get('DOTFILES_FORCE') == '1'


class PreviewError(ValueError):
    """A fixed, safe diagnostic; unlike arbitrary renderer errors."""


def within(path, root):
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def label(path):
    if within(path, CONFIG):
        return '$XDG_CONFIG_HOME/' + str(path.relative_to(CONFIG))
    if within(path, HOME):
        return '~/' + str(path.relative_to(HOME))
    return '[outside HOME: withheld]'


def safe(path):
    if not within(path, HOME) or '..' in path.parts:
        return False
    return within(path.parent.resolve(), HOME.resolve())


def digest(path):
    if path.is_symlink():
        return 'link:' + os.readlink(path)
    if not path.is_file():
        return 'missing'
    return hashlib.sha256(path.read_bytes()).hexdigest()


def owned():
    result = {}
    manifest = STATE / 'managed.tsv'
    if manifest.is_file():
        for row in manifest.read_text().splitlines():
            fields = row.split('\t')
            if len(fields) != 2 or not safe(Path(fields[-1])):
                raise PreviewError('Invalid ownership metadata; paths withheld.')
            result[Path(fields[1])] = fields[0]
    return result


def public_lines():
    # Even a previously managed file may now contain credentials. Never trust its
    # ownership hash as proof that its contents are public.
    result = set()
    environment = dict(os.environ, GIT_OPTIONAL_LOCKS='0')
    listing = subprocess.run(['git', '-C', str(SOURCE), 'ls-tree', '-r', '--name-only', 'HEAD', '--', 'home'],
                             text=True, capture_output=True, env=environment)
    if listing.returncode:
        return result
    for relative in listing.stdout.splitlines():
        entry = subprocess.run(['git', '-C', str(SOURCE), 'show', 'HEAD:' + relative],
                               text=True, capture_output=True, env=environment)
        if not entry.returncode:
            result.update(entry.stdout.splitlines())

    return result


def safe_rendering():
    # Read-only flags do not prevent template output/secret helpers from running.
    # This repository has one simple environment-path template. Require manual
    # review before evaluating any additional template capability in a preview.
    for root in (SOURCE, SOURCE / 'home', SOURCE / 'home/dot_config'):
        for name in ('.chezmoiexternal.toml', '.chezmoiexternal.yaml', '.chezmoi.toml.tmpl', '.chezmoi.yaml.tmpl'):
            if (root / name).exists():
                return False
    for path in (SOURCE / 'home').rglob('*'):
        if path.is_file() and not path.is_symlink():
            text = path.read_text(errors='replace')
            if path == SOURCE / 'home/dot_gitconfig.tmpl':
                for suffix in ('git/ignore', 'dotfiles/local/gitconfig'):
                    text = text.replace('{{ printf "%s/' + suffix + '" (env "XDG_CONFIG_HOME") | quote }}', '')
            if '{{' in text or '}}' in text:
                return False
    return True


def diff(old, new, allowed):
    old_lines, new_lines = old.splitlines(), new.splitlines()
    for kind, start, end, next_start, next_end in difflib.SequenceMatcher(
            a=old_lines, b=new_lines, autojunk=False).get_opcodes():
        if kind == 'equal':
            continue
        print(f'  DIFF old lines {start + 1}:{end}, target lines {next_start + 1}:{next_end}')
        for prefix, lines in (('-', old_lines[start:end]), ('+', new_lines[next_start:next_end])):
            hidden = 0
            for line in lines:
                if line and line in allowed:
                    if hidden:
                        print(f'  {prefix} [{hidden} private/local or rendered lines withheld]')
                        hidden = 0
                    print(f'  {prefix} {line}')
                else:
                    hidden += 1
            if hidden:
                print(f'  {prefix} [{hidden} private/local or rendered lines withheld]')


def target_state(scratch):
    if not safe_rendering():
        raise PreviewError('Additional template capabilities require manual review.')
    result = {}
    for index, (source, destination) in enumerate(((SOURCE, HOME), (SOURCE / 'home/dot_config', CONFIG))):
        command = ['chezmoi', '--source', str(source), '--destination', str(destination),
                   '--config', '/dev/null', '--config-format=toml',
                   '--persistent-state', str(scratch / f'{index}.db'),
                   '--cache', str(scratch / 'cache'), '--refresh-externals=never',
                   '--skip-secrets', '--dry-run', '--no-tty', '--no-pager',
                   'dump', '--format=json', '--include=files,symlinks']
        process = subprocess.run(command, text=True, capture_output=True)
        if process.returncode:
            raise PreviewError('Cannot render chezmoi target state; diagnostic values withheld. Check chezmoi locally.')
        for relative, entry in json.loads(process.stdout).items():
            path = destination / relative
            if not safe(path):
                raise PreviewError('Target directory escapes HOME; resolve the symlink conflict first.')
            result[path] = entry
    result[HOME / '.local/bin/dotfiles'] = {'type': 'symlink', 'target': str(SOURCE / 'bin/dotfiles')}
    return result


def compare(path, target, ownership, allowed, operation):
    if not safe(path):
        print('BLOCKED target directory escapes HOME (path withheld).')
        return True
    if path.exists() and path.is_dir() and not path.is_symlink():
        print(f'BLOCKED {label(path)}: directory conflicts with a managed file.')
        return True
    exists = path.exists() or path.is_symlink()
    changed_owned = path in ownership and digest(path) != ownership[path]
    if changed_owned and (operation == 'uninstall' or not FORCE):
        print(f'BLOCKED {label(path)}: locally modified owned file; preserve it or review --force for repair.')
        return True
    if target is None:
        if exists:
            print(f'PLAN REMOVE {label(path)}')
        else:
            print(f'UNCHANGED {label(path)}: already absent.')
        return False
    if target['type'] == 'symlink':
        equal = path.is_symlink() and os.readlink(path) == target['target']
        print(f'{"UNCHANGED" if equal else "PLAN REPLACE" if exists else "PLAN CREATE"} {label(path)} (symlink destination withheld)')
        return False
    desired = target.get('contents', '')
    previous = path.read_text(errors='replace') if path.is_file() and not path.is_symlink() else ''
    mode = stat.S_IMODE(path.stat().st_mode) if exists and not path.is_symlink() else None
    equal = exists and not path.is_symlink() and previous == desired and mode == target.get('perm', mode)
    print(f'{"UNCHANGED" if equal else "PLAN " + ("RESTORE" if operation in ("uninstall", "recover") else "REPLACE" if exists else "CREATE")} {label(path)}')
    if changed_owned:
        print('  WARNING --force would replace locally modified contents after private backup.')
    if not equal:
        diff(previous, desired, allowed)
        if mode != target.get('perm', mode):
            print(f'  MODE target {target["perm"]:04o}')
    return False


def restored(path, root):
    backup = root / path.relative_to(HOME)
    if not safe(backup):
        raise PreviewError('Recovery backup escapes HOME.')
    if backup.is_symlink():
        return {'type': 'symlink', 'target': os.readlink(backup)}
    if backup.is_file():
        return {'type': 'file', 'contents': backup.read_text(errors='replace'),
                'perm': stat.S_IMODE(backup.stat().st_mode)}
    return None


def main():
    operation = sys.argv[1]
    print('Configuration preview: public source lines only; private values and symlink destinations withheld.')
    ownership = owned()
    allowed = public_lines()
    blocked = False
    if operation in ('install', 'repair', 'update', 'sync'):
        if operation in ('update', 'sync'):
            print('NEEDS INFO incoming revision, successful Verify CI, and its diff require a fetch; no network or Git refs changed.')
            print('The following compares the current checkout only, not incoming changes.')
        with tempfile.TemporaryDirectory(prefix='dotfiles-preview-') as temp:
            targets = target_state(Path(temp))
        for path, target in sorted(targets.items()):
            blocked |= compare(path, target, ownership, allowed, operation)
        for path in sorted(ownership.keys() - targets.keys()):
            blocked |= compare(path, restored(path, STATE / 'originals'), ownership, allowed, 'uninstall')
        if operation == 'install' and (HOME / '.gitconfig').is_file():
            print('PLAN preserve existing Git settings in a private include; values withheld.')
        if (STATE / 'transaction').exists():
            print('BLOCKED interrupted transaction: run dotfiles recover before application.')
            blocked = True
    elif operation in ('uninstall', 'recover'):
        paths = ownership
        root = STATE / 'originals'
        if operation == 'recover':
            root = STATE / 'transaction/files'
            journal = STATE / 'transaction/paths'
            if not journal.is_file():
                raise PreviewError('No recovery transaction exists.')
            paths = {Path(line): '' for line in journal.read_text().splitlines()}
        for path in sorted(paths):
            if not safe(path):
                raise PreviewError('Recovery target escapes HOME.')
            blocked |= compare(path, restored(path, root), ownership if operation == 'uninstall' else {}, allowed, operation)
        if not paths:
            print('UNCHANGED no managed files to restore.')
        if operation == 'recover':
            print('PLAN restore previous ownership and revision metadata from the transaction.')
    else:
        raise PreviewError('Unsupported configuration preview.')
    return int(blocked)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except PreviewError as error:
        print("NEEDS INFO " + str(error), file=sys.stderr)
        sys.exit(1)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        # Rendering errors and malformed metadata can contain arbitrary private
        # values. Keep error output deliberately content-free.
        print('NEEDS INFO unable to produce a safe preview; verify chezmoi, target paths, and local metadata.', file=sys.stderr)
        sys.exit(1)
