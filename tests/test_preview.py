"""Preview is exercised through the CLI against disposable homes and repositories."""
import hashlib
import os
import pathlib
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PRIVATE = 'PRIVATE_PREVIEW_FIXTURE_DO_NOT_PRINT'
PUBLIC = 'PUBLIC_PREVIEW_FIXTURE_ADDITION'


def tree_snapshot(root):
    entries = {}
    if not root.exists():
        return entries
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in dirs + files:
            path = pathlib.Path(directory) / name
            metadata = path.lstat()
            if stat.S_ISLNK(metadata.st_mode):
                content = os.readlink(path)
            elif stat.S_ISREG(metadata.st_mode):
                content = hashlib.sha256(path.read_bytes()).hexdigest()
            else:
                content = None
            entries[str(path.relative_to(root))] = (stat.S_IFMT(metadata.st_mode),
                                                    stat.S_IMODE(metadata.st_mode),
                                                    metadata.st_mtime_ns, content)
    return entries


class Preview(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='dotfiles-preview-test-')
        self.addCleanup(self.tmp.cleanup)
        self.base = pathlib.Path(self.tmp.name)
        self.home = self.base / 'home with spaces'
        self.home.mkdir()
        self.source = self.base / 'source'
        shutil.copytree(ROOT, self.source, ignore=shutil.ignore_patterns('.git', '__pycache__'))
        self.env = dict(os.environ, HOME=str(self.home), XDG_CONFIG_HOME=str(self.home / '.config'),
                        XDG_STATE_HOME=str(self.home / '.local/state'), XDG_CACHE_HOME=str(self.home / '.cache'),
                        XDG_DATA_HOME=str(self.home / '.local/share'), DOTFILES_SOURCE=str(self.source),
                        DOTFILES_CONFIG=str(self.home / '.config/dotfiles'),
                        DOTFILES_STATE=str(self.home / '.local/state/dotfiles'),
                        DOTFILES_TESTING='1', DOTFILES_MODE='non-interactive', GIT_OPTIONAL_LOCKS='1',
                        GIT_AUTHOR_NAME='fixture', GIT_COMMITTER_NAME='fixture',
                        GIT_AUTHOR_EMAIL='fixture@users.noreply.github.com',
                        GIT_COMMITTER_EMAIL='fixture@users.noreply.github.com')
        self.real_git = shutil.which('git')
        self.git('init', '-q', '-b', 'master')
        # Background maintenance can mutate .git during read-only snapshots.
        self.git('config', 'maintenance.auto', 'false')
        self.git('config', 'gc.auto', '0')
        self.git('add', '.')
        self.git('commit', '-qm', 'fixture')
        self.mock_bin = self.base / 'mock-bin'
        self.mock_bin.mkdir()
        for command in ('chezmoi', 'python3', 'awk', 'sed', 'cut', 'sort', 'tr', 'grep', 'dirname',
                        'basename', 'mkdir', 'mktemp', 'chmod', 'cp', 'mv', 'rm', 'rmdir', 'ln',
                        'readlink', 'date', 'ps', 'hostname', 'sha256sum', 'shasum', 'id', 'find',
                        'head', 'tail', 'cat', 'env', 'sh', 'pwd', 'cmp', 'touch', 'jq'):
            executable = shutil.which(command)
            if executable:
                (self.mock_bin / command).symlink_to(executable)
        self.forbidden = self.base / 'forbidden-calls'
        self.env.update(PATH=str(self.mock_bin), DOTFILES_FORBIDDEN_LOG=str(self.forbidden),
                        DOTFILES_REAL_GIT=self.real_git)
        for name in ('apt-get', 'dnf', 'sudo', 'curl', 'launchctl', 'systemctl', 'crontab', 'brew', 'flatpak'):
            script = self.mock_bin / name
            script.write_text('#!/bin/sh\ncase "$0:$*" in\n*/brew:list*|*/brew:info*|*/brew:uses*|*/brew:--prefix*|*/flatpak:info*|*/flatpak:remotes*|*/flatpak:list*|*/launchctl:print*|*/launchctl:list*|*/systemctl:*show-environment*|*/systemctl:*is-active*|*/crontab:-l) exit 1 ;;\nesac\nprintf "%s\\n" "$0 $*" >> "$DOTFILES_FORBIDDEN_LOG"\nexit 97\n')
            script.chmod(0o755)
        (self.mock_bin / 'uname').write_text('#!/bin/sh\ncase "$1" in -s) printf "Linux\\n" ;; -m) printf "x86_64\\n" ;; esac\n')
        (self.mock_bin / 'uname').chmod(0o755)
        (self.mock_bin / 'apt-cache').write_text('#!/bin/sh\ncase "$1" in rdepends) printf "package\\nReverse Depends:\\n" ;; *) printf "Package: fixture\\nVersion: 1\\n" ;; esac\n')
        (self.mock_bin / 'apt-cache').chmod(0o755)
        (self.mock_bin / 'dpkg-query').write_text('#!/bin/sh\n[ "${DOTFILES_PREVIEW_PACKAGE_INSTALLED:-0}" = 1 ] || exit 1\nprintf "install ok installed"\n')
        (self.mock_bin / 'dpkg-query').chmod(0o755)
        git = self.mock_bin / 'git'
        git.write_text('#!' + sys.executable + '\n' + '''import os, subprocess, sys
args = sys.argv[1:]
if any(arg in ('fetch', 'pull', 'push', 'merge', 'reset') for arg in args):
    with open(os.environ['DOTFILES_FORBIDDEN_LOG'], 'a') as log:
        log.write('git mutation attempted\\n')
    sys.exit(97)
sys.exit(subprocess.call([os.environ['DOTFILES_REAL_GIT'], *args]))
''')
        git.chmod(0o755)

    def git(self, *args):
        result = subprocess.run([self.real_git, '-c', 'core.hooksPath=/dev/null', '-C', str(self.source), *args],
                                env=self.env, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def run_cli(self, *args, preview=True):
        command = [str(self.source / 'bin/dotfiles'), *args, '--non-interactive']
        if preview:
            command.append('--dry-run')
        before = (tree_snapshot(self.home), tree_snapshot(self.source))
        result = subprocess.run(command, env=self.env, cwd=self.home,
                                capture_output=True, text=True, timeout=45)
        if preview:
            self.assertEqual((tree_snapshot(self.home), tree_snapshot(self.source)), before,
                             'Preview changed home, state, cache, selection, or repository')
            self.assertFalse(self.forbidden.exists(), 'Preview invoked a package/scheduler/network mutation')
            self.assertNotIn(PRIVATE, result.stdout + result.stderr)
        return result

    def status(self, result, token, path):
        self.assertRegex(result.stdout + result.stderr, '(?im)' + token + r'[^\n]*' + path)

    def installed(self):
        # Actual fixture installation is needed to obtain authentic ownership/backups.
        original = '# original ' + PRIVATE + '\n'
        (self.home / '.bashrc').write_text(original)
        result = self.run_cli('install', '--profiles', 'shell', preview=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        if self.forbidden.exists():
            self.forbidden.unlink()

    def test_new_install_previews_public_additions_without_creating_state(self):
        (self.source / 'home/dot_preview_fixture').write_text(PUBLIC + '\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'public fixture addition')
        result = self.run_cli('install', '--profiles', 'shell,php', '--sync')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.status(result, 'CREATE', r'\.bashrc')
        self.status(result, 'CREATE', r'\.preview_fixture')
        self.assertIn(PUBLIC, result.stdout)
        self.assertEqual(list(self.home.iterdir()), [])

    def test_private_replacement_values_and_external_diff_command_are_hidden(self):
        (self.home / '.bashrc').write_text('# ' + PRIVATE + '\n')
        (self.home / '.bashrc').chmod(0o600)
        config = pathlib.Path(self.env['DOTFILES_CONFIG'])
        config.mkdir(parents=True)
        diff = self.base / 'external-diff'
        diff.write_text('#!/bin/sh\nprintf unsafe >> "$DOTFILES_FORBIDDEN_LOG"\n')
        diff.chmod(0o755)
        (config / 'chezmoi.toml').write_text('[diff]\ncommand = "' + str(diff) + '"\n')
        (self.home / '.private-link').symlink_to(self.home / '.bashrc')
        result = self.run_cli('install', '--profiles', 'shell')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.status(result, 'REPLACE', r'\.bashrc')

    def test_unchanged_and_owned_modified_files_are_distinguished(self):
        self.installed()
        result = self.run_cli('repair')
        self.status(result, 'UNCHANGED', r'\.bashrc')
        target = self.home / '.bashrc'
        target.write_text(target.read_text() + '# ' + PRIVATE + '\n')
        result = self.run_cli('repair')
        self.status(result, 'BLOCKED', r'\.bashrc')
        result = self.run_cli('repair', '--force')
        self.status(result, 'REPLACE', r'\.bashrc')

    def test_directory_conflict_is_blocked(self):
        (self.home / '.bashrc').mkdir()
        (self.home / '.bashrc/private').write_text(PRIVATE)
        result = self.run_cli('install', '--profiles', 'shell')
        self.status(result, 'BLOCKED', r'\.bashrc')

    def test_uninstall_reports_backup_restore_without_private_contents(self):
        self.installed()
        result = self.run_cli('uninstall')
        self.status(result, 'RESTORE', r'\.bashrc')
        self.status(result, 'REMOVE', r'\.inputrc')

    def test_future_sync_requires_fetch_and_ci_information_without_fetching(self):
        self.installed()
        result = self.run_cli('sync')
        self.assertRegex(result.stdout + result.stderr, r'(?i)NEEDS(?:_| )?INFO')
        self.assertRegex(result.stdout + result.stderr, r'(?i)fetch|CI')

    def test_unknown_template_command_is_not_evaluated(self):
        command = self.base / 'template-side-effect'
        command.write_text('#!/bin/sh\nprintf unsafe >> "$DOTFILES_FORBIDDEN_LOG"\nprintf "' + PRIVATE + '"\n')
        command.chmod(0o755)
        (self.source / 'home/dot_template_fixture.tmpl').write_text('{{ output "' + str(command) + '" }}\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'template fixture')
        result = self.run_cli('install', '--profiles', 'shell')
        self.assertRegex(result.stdout + result.stderr, r'(?i)NEEDS(?:_| )?INFO|BLOCKED')
        self.assertNotEqual(result.returncode, 0)

    def test_recovery_preview_restores_snapshot_without_applying_it(self):
        self.installed()
        target = self.home / '.inputrc'
        transaction = pathlib.Path(self.env['DOTFILES_STATE']) / 'transaction'
        (transaction / 'files').mkdir(parents=True)
        (transaction / 'files/.inputrc').write_bytes(target.read_bytes())
        (transaction / 'paths').write_text(str(target) + '\n')
        target.write_text(PRIVATE + '\n')
        result = self.run_cli('recover')
        self.status(result, 'RESTORE', r'\.inputrc')
        self.assertIn('metadata', result.stdout)

    def test_owned_package_operations_are_planned_without_installers(self):
        state = pathlib.Path(self.env['DOTFILES_STATE'])
        state.mkdir(parents=True)
        (state / 'packages').write_text('ripgrep\tapt\tripgrep\tcreated-by-dotfiles\nfirefox\tapt\tfirefox\tcreated-by-dotfiles\n')
        self.env['DOTFILES_PREVIEW_PACKAGE_INSTALLED'] = '1'
        for action, target in [('tools', 'ripgrep'), ('apps', 'firefox')]:
            for operation in ('update', 'remove'):
                result = self.run_cli(action, operation, target)
                self.assertRegex(result.stdout + result.stderr, r'(?i)PLAN ' + operation)

    def test_macos_existing_app_probe_does_not_create_a_launcher(self):
        (self.mock_bin / 'uname').write_text('#!/bin/sh\ncase "$1" in -s) printf "Darwin\n" ;; -m) printf "arm64\n" ;; esac\n')
        application = self.home / 'Applications/Firefox.app/Contents/MacOS/firefox'
        application.parent.mkdir(parents=True)
        application.write_text('#!/bin/sh\nexit 0\n')
        application.chmod(0o755)
        result = self.run_cli('apps', 'install', 'firefox')
        self.status(result, 'UNCHANGED', 'firefox')
        self.assertFalse((self.home / '.local/bin/firefox').exists())

    def test_tool_and_app_lifecycle_preview_never_runs_installers(self):
        for action, target in [('tools', 'ripgrep'), ('apps', 'firefox')]:
            for operation in ('install', 'update', 'remove'):
                with self.subTest(action=action, operation=operation):
                    result = self.run_cli(action, operation, target)
                    self.assertRegex(result.stdout + result.stderr,
                                     r'(?i)INSTALL|UPDATE|REMOVE|BLOCKED|UNCHANGED|NEEDS(?:_| )?INFO')
