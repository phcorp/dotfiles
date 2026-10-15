#!/usr/bin/env python3
"""Private Git setup. Values never appear in diagnostics or public source."""
import base64
import hashlib
import os
import pathlib
import re
import shutil
import stat
import subprocess
import sys

HOME = pathlib.Path(os.environ['HOME']).absolute()
CONFIG = pathlib.Path(os.environ['DOTFILES_CONFIG'])
STATE = pathlib.Path(os.environ['DOTFILES_STATE'])
ROOT = CONFIG / 'local/git'
OUTPUT = ROOT / 'config'
INPUT = ROOT / 'setup-input.gitconfig'
KEYS = {'user.name', 'user.email', 'user.useconfigonly', 'user.signingkey',
        'gpg.format', 'commit.gpgsign', 'tag.gpgsign', 'gpg.ssh.allowedsignersfile',
        'credential.helper', 'pull.ff'}


class SetupError(Exception):
    pass


def error(message):
    raise SetupError(message)


def run(args, **kwargs):
    result = subprocess.run(args, capture_output=True, **kwargs)
    if result.returncode:
        error('Git setup could not validate configuration; inspect it locally.')
    return result.stdout


def git(*args):
    return run(['git', *args], text=True, cwd=HOME)


def safe(path, private=False, exists=True):
    path = pathlib.Path(os.path.expanduser(str(path)))
    if not path.is_absolute():
        error('Git setup paths must be absolute or HOME-relative.')
    if '..' in path.parts or any(c in str(path) for c in '\n\r\t'):
        error('Unsafe Git setup path.')
    try:
        path.relative_to(HOME)
    except ValueError:
        error('Git setup paths must remain inside HOME.')
    for parent in [path, *path.parents]:
        if parent == HOME.parent:
            break
        if parent.is_symlink():
            error('Git setup refuses symlinked files or directories.')
    if not path.exists():
        if exists:
            error('Required private Git setup file is missing.')
        return path
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
        error('Git setup requires regular files owned by the current user.')
    if private and stat.S_IMODE(info.st_mode) not in (0o400, 0o600):
        error('Private Git configuration requires owner-only permissions (chmod 600).')
    return path


def entries(path):
    raw = run(['git', 'config', '--no-includes', '--file', '-', '--null', '--list'],
              text=True, input=path.read_text(), cwd=HOME)
    result = []
    for record in raw.split('\0'):
        if not record:
            continue
        if '\n' not in record:
            error('Git setup requires explicit configuration values.')
        key, value = record.split('\n', 1)
        if any(c in value for c in '\n\r\0') or (not value and key != 'credential.helper'):
            error('Git setup contains an invalid value.')
        result.append((key, value))
    return result


def effective():
    result = {}
    for key in KEYS:
        query = subprocess.run(['git', 'config', '--global', '--includes', '--get', key],
                               text=True, capture_output=True, cwd=HOME)
        if query.returncode not in (0, 1):
            error('Existing Git configuration cannot be read; inspect it locally.')
        if query.returncode == 0:
            result[key] = query.stdout.rstrip('\n')
    return result


def signing(values, preview=False):
    enabled = any(values.get(k, '').lower() in ('true', 'yes', 'on', '1')
                  for k in ('commit.gpgsign', 'tag.gpgsign'))
    if not enabled:
        return
    key = values.get('user.signingkey', '')
    kind = values.get('gpg.format', 'openpgp')
    if kind == 'ssh':
        if not shutil.which('ssh-keygen'):
            error('SSH signing requires existing OpenSSH tools.')
        version = git('--version')
        numbers = re.search(r'(\d+)\.(\d+)', version)
        if not numbers or tuple(map(int, numbers.groups())) < (2, 34):
            error('SSH signing requires Git 2.34 or newer.')
        public = safe(key)
        if public.suffix != '.pub':
            error('SSH signing requires an existing public .pub key, never a private key.')
        parts = public.read_text().split()
        if len(parts) < 2 or not re.fullmatch(r'(ssh-|ecdsa-|sk-)[A-Za-z0-9@._+-]+', parts[0]):
            error('Invalid SSH public signing key.')
        try:
            base64.b64decode(parts[1], validate=True)
        except ValueError:
            error('Invalid SSH public signing key.')
        # ssh-keygen reads only the selected public file; never a private key.
        run(['ssh-keygen', '-l', '-f', '/dev/stdin'],
            input=(parts[0] + ' ' + parts[1] + '\n').encode())
        companion = public.with_suffix('')
        available = (companion.is_file() and not companion.is_symlink()
                     and companion.stat().st_uid == os.getuid()
                     and stat.S_IMODE(companion.stat().st_mode) in (0o400, 0o600))
        if not available and shutil.which('ssh-add'):
            agent = subprocess.run(['ssh-add', '-L'], capture_output=True, text=True)
            available = agent.returncode == 0 and any(line.split()[:2] == parts[:2] for line in agent.stdout.splitlines())
        if not available:
            error('SSH signing requires the matching local private key or an available agent identity; no key was generated.')
    elif kind == 'openpgp':
        if not shutil.which('gpg') or not re.fullmatch(r'[A-Fa-f0-9]{16,64}', key):
            error('GPG signing requires an existing GPG tool and key fingerprint.')
        if preview:
            print('NEEDS INFO GPG signing identity availability is checked when applying; no keyring was opened.')
        else:
            import time
            output = run(['gpg', '--batch', '--no-auto-check-trustdb', '--with-colons', '--list-secret-keys', key], text=True)
            usable = False
            primary_valid = False
            for line in output.splitlines():
                fields = line.split(':')
                if fields[0] == 'sec':
                    primary_valid = False
                if len(fields) > 11 and fields[0] in ('sec', 'ssb') and fields[1] not in ('r', 'e', 'd'):
                    unexpired = not fields[6] or (fields[6].isdigit() and int(fields[6]) > time.time())
                    if fields[0] == 'sec':
                        primary_valid = unexpired and 'D' not in fields[11]
                    if primary_valid and unexpired and 's' in fields[11].lower() and 'D' not in fields[11]:
                        usable = True
            if not usable:
                error('No usable GPG signing identity is available.')
    else:
        error('Choose SSH or OpenPGP signing.')
    if values.get('gpg.ssh.allowedsignersfile'):
        safe(values['gpg.ssh.allowedsignersfile'], private=True)


def validate(rows, inherited, profile=False, preview=False, staged_profiles=None):
    seen = set()
    values = dict(inherited)
    profiles = []
    normalized = []
    for key, value in rows:
        if any(ord(c) < 32 or ord(c) == 127 for c in value):
            error('Git setup values must not contain control characters.')
        if key == 'credential.helper' and not value:
            continue
        if key in seen:
            error('Duplicate Git setup option; inspect the private input locally.')
        seen.add(key)
        if key.lower().startswith('includeif.') and key.lower().endswith('.path') and not profile:
            condition = key[len('includeif.'):-len('.path')]
            if not condition.startswith('gitdir:'):
                error('Git profiles require native gitdir directory conditions.')
            directory = condition[len('gitdir:'):]
            if not directory.endswith('/') or any(c in directory for c in '*?[]\\'):
                error('Git profile directories must be literal directories ending in a slash.')
            directory_path = safe_directory(directory)
            path = safe(value, private=True, exists=not (staged_profiles and value in staged_profiles))
            profiles.append(path)
            normalized.append(('includeIf.gitdir:' + str(directory_path) + '/.path', str(path)))
            continue
        if key not in KEYS or (profile and key in ('credential.helper', 'pull.ff', 'user.useconfigonly')):
            error('Unsupported Git setup option; inspect the private input locally.')
        if key in ('commit.gpgsign', 'tag.gpgsign', 'user.useconfigonly'):
            if value.lower() not in ('true', 'false', 'yes', 'no', 'on', 'off', '1', '0'):
                error('Invalid Git boolean setting.')
        if key == 'user.email' and not re.fullmatch(r'[^@\s]+@[^@\s]+', value):
            error('Invalid Git email; review it locally.')
        if key == 'user.signingkey' and not re.fullmatch(r'[A-Fa-f0-9]{16,64}', value):
            public = safe(value, exists=False)
            if public.suffix != '.pub':
                error('Signing requires a public .pub file or GPG fingerprint; never private key material.')
        if key == 'gpg.format' and value not in ('ssh', 'openpgp'):
            error('Choose SSH or OpenPGP signing.')
        if key == 'pull.ff' and value != 'only':
            error('Git setup uses fast-forward-only pulls.')
        if key == 'credential.helper':
            if value not in ('osxkeychain', 'libsecret', 'manager', 'manager-core'):
                error('Choose an existing secure credential helper; shell commands and plaintext storage are not accepted.')
            executable = 'git-credential-' + value
            execution_path = pathlib.Path(git('--exec-path').strip()) / executable
            if not shutil.which(executable) and not os.access(execution_path, os.X_OK):
                error('Selected secure credential helper is unavailable; keep existing authentication or configure it separately.')
        values[key] = value
        normalized.append((key, value))
    # Validate new signing choices, not unrelated existing credentials/settings.
    if any(k in seen for k in ('commit.gpgsign', 'tag.gpgsign', 'user.signingkey', 'gpg.format', 'gpg.ssh.allowedsignersfile')):
        signing(values, preview=preview)
    # Profiles follow the global settings, regardless of source section order.
    if profiles:
        for path in profiles:
            source = staged_profiles.get(str(path), path) if staged_profiles else path
            validate(entries(source), values, profile=True, preview=preview)
        normalized = [(k, v) for k, v in normalized if not k.lower().startswith('includeif.')] + [
            (k, v) for k, v in normalized if k.lower().startswith('includeif.')]
    return normalized


def safe_directory(value):
    path = pathlib.Path(os.path.expanduser(value))
    if not path.is_absolute() or '..' in path.parts or any(c in str(path) for c in '*?[]\\'):
        error('Git profile directories must remain inside HOME.')
    try:
        path.resolve().relative_to(HOME.resolve())
    except ValueError:
        error('Git profile directories must remain inside HOME.')
    if any(c in str(path) for c in '\n\r\t'):
        error('Unsafe Git profile directory.')
    return path.resolve()


def setup_key(key):
    if key.lower().startswith('includeif.') and key.lower().endswith('.path'):
        condition = key[len('includeif.'):-len('.path')]
        if condition.startswith('gitdir:'):
            directory = condition[len('gitdir:'):]
            if not directory.endswith('/'):
                error('Git profile directories must end in a slash.')
            return 'includeIf.gitdir:' + str(safe_directory(directory)) + '/.path'
        return 'includeIf.' + condition + '.path'
    return key.lower()


def ownership():
    ledger = STATE / 'git-setup.tsv'
    if not ledger.exists():
        if OUTPUT.exists():
            error('Existing private Git setup has no ownership record; review it locally before replacing it.')
        return []
    rows = []
    seen = set()
    for line in ledger.read_text().splitlines():
        pieces = line.split('\t')
        if len(pieces) != 2 or not re.fullmatch(r'[0-9a-f]{64}', pieces[0]):
            error('Invalid private Git ownership record; preserve it for review.')
        digest, target = pieces
        path = pathlib.Path(target)
        valid_profile = path.parent == ROOT / 'profiles' and re.fullmatch(r'[A-Za-z0-9_-]+\.gitconfig', path.name)
        if (path != OUTPUT and not valid_profile) or path in seen:
            error('Invalid private Git ownership target; preserve it for review.')
        seen.add(path)
        rows.append((digest, path))
    if OUTPUT.exists() and OUTPUT not in seen:
        error('Private Git ownership is incomplete; preserve it for review.')
    return rows


def managed():
    override = os.environ.get('GIT_CONFIG_GLOBAL')
    if override is not None and pathlib.Path(override).expanduser().resolve() != (HOME / '.gitconfig').resolve():
        error('Git global override bypasses managed configuration; resolve it locally before setup.')
    ledger = STATE / 'managed.tsv'
    if not ledger.is_file() or not (HOME / '.gitconfig').is_file():
        error('Install dotfiles before running Git setup.')
    includes = git('config', '--file', str(HOME / '.gitconfig'), '--no-includes', '--get-all', 'include.path')
    if str(OUTPUT) not in includes.splitlines():
        error('Apply current dotfiles configuration before running Git setup.')
    safe(OUTPUT, private=True, exists=False)
    safe(STATE / 'git-setup.tsv', private=True, exists=False)
    for digest, path in ownership():
        if path == OUTPUT and hashlib.sha256(safe(path, private=True).read_bytes()).hexdigest() != digest:
            error('Private Git setup was modified; preserve or review local edits before setup.')


def write_config(path, rows):
    path.touch(mode=0o600)
    for key, value in rows:
        # Private values go over stdin, never argv or a shell command.
        # Git --file has no stdin value interface, so serialize using native
        # quoting instead of spawning commands with secret-bearing arguments.
        section, variable = key.rsplit('.', 1)
        if section.lower().startswith('includeif.'):
            subsection = section[len('includeIf.'):].replace('\\', '\\\\').replace('"', '\\"')
            heading = '[includeIf "' + subsection + '"]'
        elif section.lower() == 'gpg.ssh':
            heading = '[gpg "ssh"]'
        else:
            heading = '[' + section + ']'
        quoted = value.replace('\\', '\\\\').replace('"', '\\"').replace('\t', '\\t')
        with path.open('a') as stream:
            if key == 'credential.helper' and value:
                stream.write('[credential]\n    helper = ""\n')
            stream.write(heading + '\n    ' + variable + ' = "' + quoted + '"\n')
    os.chmod(path, 0o600)


def prompt(tty, text):
    tty.write(text + ': ')
    tty.flush()
    with open('/dev/tty', 'r') as reader:
        answer = reader.readline()
    if not answer:
        error('Git setup cancelled before application.')
    return answer.rstrip('\n')


def interactive(stage):
    with open('/dev/tty', 'w') as tty:
        tty.write('Git setup: existing SSH configuration and credentials are retained.\n')
        rows = []
        baseline = effective()
        if baseline.get('user.name') and baseline.get('user.email'):
            tty.write('Current identity (local terminal only):\n' + baseline['user.name'] + ' <' + baseline['user.email'] + '>\n')
        if prompt(tty, 'Change global identity? [y/N]').lower() == 'y':
            rows += [('user.name', prompt(tty, 'Git name')), ('user.email', prompt(tty, 'Git email'))]
        rows += [('pull.ff', 'only'), ('user.useconfigonly', 'true')]
        if prompt(tty, 'Change HTTPS helper? SSH and existing helpers otherwise remain unchanged [y/N]').lower() == 'y':
            rows.append(('credential.helper', prompt(tty, 'Existing secure helper (osxkeychain/libsecret/manager/manager-core)')))
        choice = prompt(tty, 'Signing: keep / off / ssh / gpg [keep]').lower()
        if choice == 'off':
            rows += [('commit.gpgsign', 'false'), ('tag.gpgsign', 'false')]
        elif choice in ('ssh', 'gpg'):
            rows += [('gpg.format', 'ssh' if choice == 'ssh' else 'openpgp'),
                     ('user.signingkey', prompt(tty, 'Existing public .pub key path' if choice == 'ssh' else 'Existing GPG fingerprint')),
                     ('commit.gpgsign', 'true')]
        elif choice not in ('', 'keep'):
            error('Choose keep, off, SSH, or GPG signing.')
        number = 0
        targets = set()
        while prompt(tty, 'Add a private directory identity profile? [y/N]').lower() == 'y':
            number += 1
            slug = prompt(tty, 'Local profile label (lowercase letters, numbers, hyphens)')
            if not re.fullmatch(r'[a-z0-9_-]+', slug):
                error('Invalid private profile label.')
            target = ROOT / 'profiles' / (slug + '.gitconfig')
            safe(target, private=True, exists=False)
            if target.exists() or target in targets:
                error('Profile already exists; edit its private file locally or select another label.')
            targets.add(target)
            directory = safe_directory(prompt(tty, 'Repository directory root'))
            profile = [('user.name', prompt(tty, 'Profile Git name')), ('user.email', prompt(tty, 'Profile Git email'))]
            validate(profile, dict(baseline, **dict(rows)), profile=True)
            write_config(stage / ('profile-' + str(number)), profile)
            with (stage / 'profiles').open('a') as stream:
                stream.write(str(number) + '\t' + str(target) + '\n')
            rows.append(('includeIf.gitdir:' + str(directory) + '/.path', str(target)))
        if prompt(tty, 'Apply these private choices? [y/N]').lower() != 'y':
            error('Git setup cancelled before application.')
        return rows


def prepare(stage, mode):
    managed()
    staged_profiles = {}
    if mode == 'interactive':
        rows = interactive(stage)
        if (stage / 'profiles').exists():
            for line in (stage / 'profiles').read_text().splitlines():
                number, target = line.split('\t')
                staged_profiles[target] = stage / ('profile-' + number)
    else:
        if not INPUT.exists():
            if mode == 'preview':
                print('NEEDS INFO Git setup: prepare private setup-input.gitconfig or use the interactive wizard.')
                return
            error('Prepare owner-only private setup-input.gitconfig before unattended Git setup.')
        rows = entries(safe(INPUT, private=True))
    # Re-running setup preserves choices not explicitly replaced.
    previous = entries(safe(OUTPUT, private=True)) if OUTPUT.exists() else []
    previous = [(k, v) for k, v in previous if k != 'credential.helper' or v]
    previous = [(setup_key(k), v) for k, v in previous]
    rows = [(setup_key(k), v) for k, v in rows]
    replacements = {k for k, _ in rows}
    merged = [(k, v) for k, v in previous if k not in replacements] + rows
    # Validate the final state so unavailable previous signers can be replaced
    # or disabled, and retained profiles inherit the new global choices.
    merged = validate(merged, effective(), preview=(mode == 'preview'), staged_profiles=staged_profiles)
    write_config(stage / 'config', merged)
    print('PLAN Git setup: private identity/profile, authentication and signing choices validated; values withheld.')
    print('PLAN preserve existing SSH configuration, remotes, credentials and legacy Git overrides.')


def snapshot(path):
    safe(path, exists=False)
    journal = STATE / 'transaction'
    relative = path.relative_to(HOME)
    destination = journal / 'files' / relative
    if path.exists():
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        shutil.copy2(path, destination)
    with (journal / 'paths').open('a') as stream:
        stream.write(str(path) + '\n')


def atomic_copy(source, target):
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = target.with_name(target.name + '.new')
    safe(temporary, exists=False)
    if temporary.exists():
        error('An unfinished private write requires review before Git setup.')
    journal_paths = STATE / 'transaction/paths'
    if journal_paths.is_file() and str(temporary) not in journal_paths.read_text().splitlines():
        snapshot(temporary)
    with temporary.open('xb') as stream:
        stream.write(source.read_bytes())
    os.chmod(temporary, 0o600)
    os.replace(temporary, target)


def apply(stage):
    managed()
    files = [(stage / 'config', OUTPUT)]
    if (stage / 'profiles').exists():
        for line in (stage / 'profiles').read_text().splitlines():
            number, target = line.split('\t')
            files.append((stage / ('profile-' + number), pathlib.Path(target)))
    ledger = STATE / 'git-setup.tsv'
    for digest, path in ownership():
        if path in (p for _, p in files):
            path = safe(path, private=True)
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                error('Private Git setup was modified; preserve or review local edits before setup.')
    for _, path in files:
        safe(path, private=True, exists=False)
    for path in [*(p for _, p in files), ledger]:
        snapshot(path)
        temporary = path.with_name(path.name + '.new')
        if temporary.exists() or temporary.is_symlink():
            error('An unfinished private write requires review before Git setup.')
        snapshot(temporary)
    for source, path in files:
        atomic_copy(source, path)
    records = []
    if ledger.exists():
        records = ledger.read_text().splitlines()
    targets = {str(p) for _, p in files}
    records = [r for r in records if r.split('\t', 1)[1] not in targets]
    for _, path in files:
        records.append(hashlib.sha256(path.read_bytes()).hexdigest() + '\t' + str(path))
    (stage / 'ledger').write_text('\n'.join(records) + '\n')
    atomic_copy(stage / 'ledger', ledger)
    print('Private Git setup applied. SSH configuration and existing credentials retained.')


def retain():
    if not OUTPUT.exists():
        return
    safe(OUTPUT, private=True)
    target = HOME / '.gitconfig'
    safe(target, exists=False)
    rows = entries(target) if target.exists() else []
    if ('include.path', str(OUTPUT)) in rows:
        return
    # Append only a native include, preserving original bytes and relative includes.
    import tempfile
    with tempfile.TemporaryDirectory(prefix='dotfiles-git-retain-') as work:
        temporary = pathlib.Path(work) / 'config'
        if target.exists():
            temporary.write_bytes(target.read_bytes() + b'\n')
        write_config(temporary, [('include.path', str(OUTPUT))])
        atomic_copy(temporary, target)


def status():
    values = effective()
    print('Git identity: ' + ('configured (values withheld).' if values.get('user.name') and values.get('user.email') else 'not configured; review Git setup.'))
    print('Git signing: ' + ('enabled (identity withheld).' if values.get('commit.gpgsign', '').lower() in ('true', 'yes', 'on', '1') else 'not enabled.'))
    print('Git authentication: existing SSH configuration and credential helpers retained; no remote checks performed.')
    print('Git pull: ' + ('fast-forward only.' if values.get('pull.ff') == 'only' else 'private override or default; review locally.'))


def main():
    action = sys.argv[1]
    if action == 'prepare':
        prepare(pathlib.Path(sys.argv[2]), sys.argv[3])
    elif action == 'apply':
        apply(pathlib.Path(sys.argv[2]))
    elif action == 'retain':
        retain()
    elif action == 'status':
        status()
    else:
        error('Unknown Git setup operation.')


if __name__ == '__main__':
    try:
        main()
    except (SetupError, OSError, ValueError, UnicodeError, IndexError):
        # Raw Git/GPG/SSH/parser errors can contain identities, domains or paths.
        problem = sys.exc_info()[1]
        print('dotfiles: ' + (str(problem) if isinstance(problem, SetupError) else 'Git setup could not finish; inspect private files locally.'), file=sys.stderr)
        sys.exit(1)
