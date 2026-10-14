import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class Sync(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='dotfiles-sync-test-')
        self.addCleanup(self.tmp.cleanup)
        self.base = pathlib.Path(self.tmp.name)
        seed = self.base / 'seed'
        shutil.copytree(ROOT, seed, ignore=shutil.ignore_patterns('.git', '__pycache__'))
        self.git_env = dict(os.environ, GIT_AUTHOR_NAME='Test', GIT_COMMITTER_NAME='Test',
                            GIT_AUTHOR_EMAIL='test@example.invalid', GIT_COMMITTER_EMAIL='test@example.invalid')
        self.git(seed, 'init', '-b', 'master')
        self.git(seed, 'add', '.')
        self.git(seed, 'commit', '-m', 'fixture')
        self.remote = self.base / 'remote.git'
        self.git(self.base, 'clone', '--bare', str(seed), str(self.remote))
        self.source = self.base / 'source'
        self.git(self.base, 'clone', str(self.remote), str(self.source))
        self.home = self.base / 'home'
        self.home.mkdir()
        self.env = dict(self.git_env, HOME=str(self.home), DOTFILES_SOURCE=str(self.source),
                        DOTFILES_CONFIG=str(self.home / '.config/dotfiles'),
                        DOTFILES_STATE=str(self.home / '.local/state/dotfiles'),
                        XDG_CONFIG_HOME=str(self.home / '.config'), XDG_STATE_HOME=str(self.home / '.local/state'),
                        DOTFILES_MODE='non-interactive', DOTFILES_TESTING='1', DOTFILES_SYNC_SKIP_CI='1')
        self.cli('install', '--non-interactive', '--profiles', 'shell')

    def git(self, cwd, *args):
        result = subprocess.run(['git', '-c', 'core.hooksPath=/dev/null', '-C', str(cwd), *args], env=self.git_env,
                                text=True, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def cli(self, *args, check=True):
        result = subprocess.run([str(self.source / 'bin/dotfiles'), *args], env=self.env,
                                cwd=self.home, text=True, capture_output=True, timeout=60)
        if check:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def test_dirty_source_refused(self):
        (self.source / 'README.md').write_text('dirty fixture\n')
        result = self.cli('sync', '--non-interactive', check=False)
        self.assertNotEqual(result.returncode, 0)

    def test_managed_edit_refused(self):
        target = self.home / '.bashrc'
        original = target.read_text() + '\n# local edit\n'
        target.write_text(original)
        result = self.cli('sync', '--non-interactive', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(target.read_text(), original)

    def test_fast_forward_applies(self):
        upstream = self.base / 'upstream'
        self.git(self.base, 'clone', str(self.remote), str(upstream))
        target = upstream / 'home/dot_inputrc'
        target.write_text(target.read_text() + '\n# synchronized fixture\n')
        self.git(upstream, 'add', '.')
        self.git(upstream, 'commit', '-m', 'update fixture')
        self.git(upstream, 'push', 'origin', 'master')
        self.cli('sync', '--non-interactive')
        self.assertIn('# synchronized fixture', (self.home / '.inputrc').read_text())
        self.assertEqual(self.git(self.source, 'rev-parse', 'HEAD'), self.git(upstream, 'rev-parse', 'HEAD'))

    def test_diverged_history_is_refused(self):
        (self.source / 'README.md').write_text('local committed change\n')
        self.git(self.source, 'add', '.')
        self.git(self.source, 'commit', '-m', 'local divergence')
        before = self.git(self.source, 'rev-parse', 'HEAD')
        result = self.cli('sync', '--non-interactive', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.git(self.source, 'rev-parse', 'HEAD'), before)

    def test_offline_remote_keeps_configuration(self):
        self.git(self.source, 'remote', 'set-url', 'origin', str(self.base / 'missing.git'))
        before = (self.home / '.inputrc').read_text()
        result = self.cli('sync', '--non-interactive', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.home / '.inputrc').read_text(), before)

    def test_concurrent_lifecycle_is_refused(self):
        state = self.home / '.local/state/dotfiles'
        (state / 'lifecycle.lock').mkdir()
        result = self.cli('repair', '--non-interactive', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue((state / 'lifecycle.lock').exists())

    def test_ci_bypass_requires_test_mode(self):
        self.env.pop('DOTFILES_TESTING')
        fake_bin = self.home / 'fixture-bin'
        fake_bin.mkdir()
        curl = fake_bin / 'curl'
        curl.write_text('#!/bin/sh\nexit 7\n')
        curl.chmod(0o755)
        self.env['PATH'] = str(fake_bin) + ':' + self.env['PATH']
        result = self.cli('sync', '--non-interactive', check=False)
        self.assertNotEqual(result.returncode, 0)
