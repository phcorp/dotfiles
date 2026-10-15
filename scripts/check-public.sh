#!/bin/sh
# Inspect only repository files; never traverse the user's home.
set -eu
cd "$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)"
python3 - <<'PY'
import pathlib, re, subprocess, sys
files = subprocess.check_output(['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard'], text=True).split('\0')
files = sorted(set(filter(None, files)))
index = {}
for record in subprocess.check_output(['git', 'ls-files', '--stage', '-z'], text=True).split('\0'):
    if record:
        metadata, name = record.split('\t', 1)
        mode, digest, stage = metadata.split()
        index[name] = (mode, stage)
roots = {'.github', 'bin', 'lib', 'home', 'scripts', 'tests', 'docs'}
names = {'README.md', 'CHANGELOG.md', 'LICENSE', 'catalog.tsv', 'bootstrap.sh', '.chezmoiroot', '.gitignore', '.gitleaks.toml'}
errors = []
def public_identity(name, email):
    match = re.fullmatch(r'(?:[0-9]+\+)?([A-Za-z0-9_.-]+(?:\[bot\])?)@users\.noreply\.github\.com', email)
    return bool(match and name == match.group(1))

# Check both upcoming commits and all history that could be pushed. Never print identities.
for variable in ('GIT_AUTHOR_IDENT', 'GIT_COMMITTER_IDENT'):
    result = subprocess.run(['git', 'var', variable], text=True, capture_output=True)
    match = re.fullmatch(r'([^<>\n]+) <([^<>\n]+)> [0-9]+ [+-][0-9]{4}\n?', result.stdout)
    if result.returncode or not match or not public_identity(match.group(1), match.group(2)):
        errors.append('Repository publication identity must use its matching GitHub noreply alias')
history = subprocess.run(['git', 'log', '--all', '--format=%an%x00%ae%x00%cn%x00%ce'],
                         text=True, capture_output=True)
if history.returncode:
    errors.append('Repository history could not be audited')
else:
    for record in history.stdout.splitlines():
        fields = record.split('\0')
        # GitHub signs web merges using this public service identity.
        github_committer = len(fields) == 4 and fields[2:] == ['GitHub', 'noreply@github.com']
        if len(fields) != 4 or not public_identity(fields[0], fields[1]) or not (public_identity(fields[2], fields[3]) or github_committer):
            errors.append('Reachable Git history contains nonpublic author or committer metadata')
            break
for name in files:
    path = pathlib.Path(name)
    if path.parts[0] not in roots and name not in names:
        errors.append(f'{name}: unapproved public path')
    if any(part in {'.env', '.ssh', '.gnupg', 'local', 'backups', 'logs'} or part.endswith(('.pem', '.key', '.p12')) for part in path.parts):
        errors.append(f'{name}: private file path')
    if path.is_symlink() or index.get(name, ('', ''))[0] == '120000':
        errors.append(f'{name}: public source symlink requires review')
        continue
    contents = []
    if name in index:
        if index[name][1] != '0':
            errors.append(f'{name}: unmerged public file cannot be audited')
            continue
        contents.append(subprocess.check_output(['git', 'show', ':' + name]))
    if path.is_file():
        contents.append(path.read_bytes())
    for content in contents:
        if b'\0' in content:
            errors.append(f'{name}: binary file requires review')
            continue
        text = content.decode('utf-8', errors='replace')
        # Pattern pieces deliberately avoid matching this checker itself.
        patterns = [r'/' + r'Users/[A-Za-z0-9_.-]+/', r'/' + r'home/[A-Za-z0-9_.-]+/',
                    r'-----BEGIN ' + r'(?:OPENSSH |RSA |EC |DSA )?PRIVATE KEY-----',
                    r'(?im)^\s*(?:name|email)\s*=\s*[^\s#\n]+']
        if any(re.search(pattern, text) for pattern in patterns):
            errors.append(f'{name}: private identity or machine-specific value')
for error in errors:
    print(error, file=sys.stderr)
sys.exit(bool(errors))
PY
