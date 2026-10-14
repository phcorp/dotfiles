"""Real process termination at transaction boundaries, using disposable Git homes."""
import json
import os
import pathlib
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def file_state(path):
    if not path.exists() and not path.is_symlink():
        return None
    metadata = path.lstat()
    value = os.readlink(path) if path.is_symlink() else path.read_bytes()
    return (stat.S_IMODE(metadata.st_mode), value)


def directory_state(root):
    result = {}
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in dirs + files:
            path = pathlib.Path(directory) / name
            result[str(path.relative_to(root))] = (stat.S_IMODE(path.lstat().st_mode),
                                                  None if path.is_dir() and not path.is_symlink() else file_state(path))
    return result


class InterruptedApply(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='dotfiles-interruption-test-')
        self.addCleanup(self.tmp.cleanup)
        self.base = pathlib.Path(self.tmp.name)
        self.seed = self.base / 'seed'
        shutil.copytree(ROOT, self.seed, ignore=shutil.ignore_patterns('.git', '__pycache__'))
        self.git_env = dict(os.environ, GIT_AUTHOR_NAME='fixture', GIT_COMMITTER_NAME='fixture',
                            GIT_AUTHOR_EMAIL='fixture@users.noreply.github.com',
                            GIT_COMMITTER_EMAIL='fixture@users.noreply.github.com', GIT_OPTIONAL_LOCKS='0')
        self.git(self.seed, 'init', '-q', '-b', 'master')
        self.git(self.seed, 'add', '.')
        self.git(self.seed, 'commit', '-qm', 'baseline')
        self.old_sha = self.git(self.seed, 'rev-parse', 'HEAD')
        self.remote = self.base / 'remote.git'
        self.git(self.base, 'clone', '--bare', str(self.seed), str(self.remote))
        self.source = self.base / 'source'
        self.git(self.base, 'clone', str(self.remote), str(self.source))
        self.home = self.base / 'home with spaces'
        self.home.mkdir()
        self.state = self.home / '.local/state/dotfiles'
        self.config = self.home / '.config/dotfiles'
        self.env = dict(self.git_env, HOME=str(self.home), DOTFILES_SOURCE=str(self.source),
                        DOTFILES_CONFIG=str(self.config), DOTFILES_STATE=str(self.state),
                        XDG_CONFIG_HOME=str(self.home / '.config'), XDG_STATE_HOME=str(self.home / '.local/state'),
                        XDG_CACHE_HOME=str(self.home / '.cache'), XDG_DATA_HOME=str(self.home / '.local/share'),
                        DOTFILES_MODE='non-interactive', DOTFILES_TESTING='1', DOTFILES_SYNC_SKIP_CI='1')
        self.cli('install', '--profiles', 'shell')
        self.metadata = [self.state / 'managed.tsv', self.state / 'applied-revision',
                         self.config / 'tools', self.config / 'profiles', self.config / 'mode',
                         self.state / 'originals.list']
        self.metadata_before = {path: file_state(path) for path in self.metadata}
        targets = [pathlib.Path(row.split('\t', 1)[1]) for row in (self.state / 'managed.tsv').read_text().splitlines()]
        self.files_before = {path: file_state(path) for path in targets}
        self.originals_before = directory_state(self.state / 'originals')
        self.shim_bin = self.base / 'shims'
        self.shim_bin.mkdir()
        self.ready = self.base / 'gate-ready'
        self.release = self.base / 'gate-release'
        real = {name: shutil.which(name) for name in ('chezmoi', 'ln', 'mv', 'rm', 'git')}
        self.env.update(DOTFILES_GATE_REALS=json.dumps(real), DOTFILES_GATE_READY=str(self.ready),
                        DOTFILES_GATE_RELEASE=str(self.release), DOTFILES_GATE_STATE=str(self.state),
                        DOTFILES_GATE_HOME=str(self.home), DOTFILES_GATE_SOURCE=str(self.source))
        wrapper = '#!' + sys.executable + '\n' + '''import json, os, pathlib, subprocess, sys, time
fixture_tool = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
kind = os.environ.get('DOTFILES_GATE_KIND', '')
state = pathlib.Path(os.environ['DOTFILES_GATE_STATE'])
source = os.environ['DOTFILES_GATE_SOURCE']
matched = False
before = False
if fixture_tool == 'git' and 'status' in args and os.environ.get('DOTFILES_GIT_STATUS_FAIL') == '1':
    print('fixture Git status unavailable', file=sys.stderr)
    sys.exit(97)
if fixture_tool == 'git' and kind == 'after_fast_forward' and 'merge' in args:
    matched = True
elif fixture_tool == 'chezmoi' and kind == 'after_home_apply' and 'apply' in args:
    matched = '--source' in args and args[args.index('--source') + 1] == source
elif fixture_tool == 'ln' and kind == 'before_command_link':
    matched = bool(args and args[-1] == os.environ['DOTFILES_GATE_HOME'] + '/.local/bin/dotfiles')
    before = True
elif fixture_tool == 'mv' and args:
    expected = {'after_managed_ledger': state / 'managed.tsv',
                'after_revision': state / 'applied-revision',
                'after_commit': state / 'transaction/committed',
                'after_source_before': state / 'transaction/source.before',
                'after_source_next': state / 'transaction/source.next'}
    matched = kind in expected and args[-1] == str(expected[kind])

def pause():
    pathlib.Path(os.environ['DOTFILES_GATE_READY']).write_text(fixture_tool + ':' + kind)
    while not pathlib.Path(os.environ['DOTFILES_GATE_RELEASE']).exists():
        time.sleep(0.02)
if matched and before:
    pause()
result = subprocess.call([json.loads(os.environ['DOTFILES_GATE_REALS'])[fixture_tool], *args])
if result == 0 and matched and not before:
    pause()
sys.exit(result)
'''
        for name in real:
            script = self.shim_bin / name
            script.write_text(wrapper)
            script.chmod(0o755)
        self.env['PATH'] = str(self.shim_bin) + ':' + self.env['PATH']

    def git(self, directory, *args):
        result = subprocess.run(['git', '-c', 'core.hooksPath=/dev/null', '-C', str(directory), *args],
                                env=self.git_env, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def cli(self, *args, check=True):
        result = subprocess.run([str(self.source / 'bin/dotfiles'), *args, '--non-interactive'],
                                env=self.env, cwd=self.home, capture_output=True, text=True, timeout=45)
        if check:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def candidate(self, sync=False):
        repository = self.seed if sync else self.source
        target = repository / 'home/dot_inputrc'
        target.write_text(target.read_text() + '\n# candidate revision fixture\n')
        (repository / 'home/dot_interruption_fixture').write_text('candidate new file\n')
        (repository / 'home/dot_profile').unlink()
        self.git(repository, 'add', '.')
        self.git(repository, 'commit', '-qm', 'candidate')
        self.new_sha = self.git(repository, 'rev-parse', 'HEAD')
        if sync:
            self.git(self.remote, 'fetch', str(repository), 'master:master')

    def kill_at(self, kind, action='repair', *options):
        self.env['DOTFILES_GATE_KIND'] = kind
        process = subprocess.Popen([str(self.source / 'bin/dotfiles'), action, *options, '--non-interactive'],
                                   env=self.env, cwd=self.home,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
        deadline = time.monotonic() + 20
        while not self.ready.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        if not self.ready.exists():
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
            stdout, stderr = process.communicate(timeout=10)
            self.fail('Fault gate was not reached: ' + stdout + stderr)
        os.killpg(process.pid, signal.SIGKILL)
        process.communicate(timeout=10)
        self.assertEqual(process.returncode, -signal.SIGKILL)
        self.assertTrue((self.state / 'transaction').is_dir())
        self.env.pop('DOTFILES_GATE_KIND')

    def recover(self):
        return self.cli('recover', '--unlock-stale')

    def assert_rolled_back(self, sync=False):
        self.assertEqual({path: file_state(path) for path in self.files_before}, self.files_before)
        self.assertEqual({path: file_state(path) for path in self.metadata}, self.metadata_before)
        self.assertEqual(directory_state(self.state / 'originals'), self.originals_before)
        self.assertFalse((self.home / '.interruption_fixture').exists())
        self.assertFalse((self.state / 'transaction').exists())
        self.assertFalse((self.state / 'lifecycle.lock').exists())
        self.assertEqual(self.git(self.source, 'rev-parse', 'HEAD'), self.old_sha if sync else self.new_sha)

    def test_partial_home_application_recovers_all_files_and_metadata(self):
        self.candidate()
        self.kill_at('after_home_apply', 'repair', '--profiles', 'shell,php')
        self.assertNotEqual((self.home / '.inputrc').read_bytes(), self.files_before[self.home / '.inputrc'][1])
        self.recover()
        self.assert_rolled_back()

    def test_command_link_boundary_recovers_removed_and_new_targets(self):
        self.candidate()
        self.kill_at('before_command_link')
        self.recover()
        self.assert_rolled_back()

    def test_managed_ledger_publish_boundary_recovers_prior_revision_pair(self):
        self.candidate()
        self.kill_at('after_managed_ledger')
        self.assertNotEqual(file_state(self.state / 'managed.tsv'), self.metadata_before[self.state / 'managed.tsv'])
        self.recover()
        self.assert_rolled_back()

    def test_revision_publish_boundary_recovers_prior_ownership_and_revision(self):
        self.candidate()
        self.kill_at('after_revision')
        self.assertEqual((self.state / 'applied-revision').read_text().strip(), self.new_sha)
        self.recover()
        self.assert_rolled_back()

    def test_interrupted_source_before_marker_recovers_without_candidate_marker(self):
        self.candidate(sync=True)
        self.kill_at('after_source_before', 'sync')
        self.assertTrue((self.state / 'transaction/source.before').exists())
        self.assertFalse((self.state / 'transaction/source.next').exists())
        self.assertFalse((self.state / 'transaction/source.ready').exists())
        self.assertEqual(self.git(self.source, 'rev-parse', 'HEAD'), self.old_sha)
        self.recover()
        self.assert_rolled_back(sync=True)

    def test_interrupted_source_next_marker_recovers_before_source_ready(self):
        self.candidate(sync=True)
        self.kill_at('after_source_next', 'sync')
        self.assertTrue((self.state / 'transaction/source.before').exists())
        self.assertTrue((self.state / 'transaction/source.next').exists())
        self.assertFalse((self.state / 'transaction/source.ready').exists())
        self.assertEqual(self.git(self.source, 'rev-parse', 'HEAD'), self.old_sha)
        self.recover()
        self.assert_rolled_back(sync=True)

    def test_sync_fast_forward_gap_recovers_source_head_without_home_changes(self):
        self.candidate(sync=True)
        self.kill_at('after_fast_forward', 'sync')
        self.assertEqual(self.git(self.source, 'rev-parse', 'HEAD'), self.new_sha)
        self.recover()
        self.assert_rolled_back(sync=True)

    def test_sync_partial_application_recovers_source_head_files_and_revision(self):
        self.candidate(sync=True)
        self.kill_at('after_revision', 'sync')
        self.recover()
        self.assert_rolled_back(sync=True)

    def test_committed_sync_recovers_cleanup_without_rolling_back_success(self):
        self.candidate(sync=True)
        self.kill_at('after_commit', 'sync')
        deployed = {path: file_state(path) for path in self.metadata}
        new_content = (self.home / '.inputrc').read_bytes()
        self.recover()
        self.assertEqual({path: file_state(path) for path in self.metadata}, deployed)
        self.assertEqual((self.home / '.inputrc').read_bytes(), new_content)
        self.assertEqual((self.state / 'applied-revision').read_text().strip(), self.new_sha)
        self.assertEqual(self.git(self.source, 'rev-parse', 'HEAD'), self.new_sha)
        self.assertTrue((self.home / '.interruption_fixture').exists())
        self.assertFalse((self.state / 'transaction').exists())
        self.assertFalse((self.state / 'lifecycle.lock').exists())

    def test_unavailable_git_status_refuses_recovery_without_clobbering_changes(self):
        self.candidate(sync=True)
        self.kill_at('after_revision', 'sync')
        private_change = 'new local change while status is unavailable\n'
        (self.source / 'README.md').write_text(private_change)
        before_metadata = {path: file_state(path) for path in self.metadata}
        before_targets = {path: file_state(path) for path in self.files_before}
        self.env['DOTFILES_GIT_STATUS_FAIL'] = '1'
        result = self.cli('recover', '--unlock-stale', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual({path: file_state(path) for path in self.metadata}, before_metadata)
        self.assertEqual({path: file_state(path) for path in self.files_before}, before_targets)
        self.assertEqual((self.source / 'README.md').read_text(), private_change)
        self.assertTrue((self.state / 'transaction').exists())
        self.assertEqual(self.git(self.source, 'rev-parse', 'HEAD'), self.new_sha)

    def test_dirty_sync_source_refuses_recovery_and_preserves_transaction(self):
        self.candidate(sync=True)
        self.kill_at('after_revision', 'sync')
        (self.source / 'README.md').write_text('new local change after interruption\n')
        before = {path: file_state(path) for path in self.metadata}
        result = self.cli('recover', '--unlock-stale', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual({path: file_state(path) for path in self.metadata}, before)
        self.assertTrue((self.state / 'transaction').exists())
        self.assertEqual(self.git(self.source, 'rev-parse', 'HEAD'), self.new_sha)
