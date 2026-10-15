"""Git setup operates only on disposable private homes; no remote/helper calls."""
import hashlib
import os
import pathlib
import pty
import select
import signal
import time
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class GitSetup(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='dotfiles-git-setup-')
        self.addCleanup(self.tmp.cleanup)
        self.home = pathlib.Path(self.tmp.name) / 'private home'
        self.home.mkdir(mode=0o700)
        self.config = self.home / 'configuration/dotfiles'
        self.state = self.home / 'state/dotfiles'
        self.env = dict(os.environ, HOME=str(self.home),
                        XDG_CONFIG_HOME=str(self.home / 'configuration'),
                        XDG_STATE_HOME=str(self.home / 'state'),
                        XDG_CACHE_HOME=str(self.home / 'cache'),
                        DOTFILES_SOURCE=str(ROOT), DOTFILES_CONFIG=str(self.config),
                        DOTFILES_STATE=str(self.state), DOTFILES_MODE='non-interactive',
                        DOTFILES_TESTING='1', GIT_CONFIG_NOSYSTEM='1',
                        GIT_CONFIG_GLOBAL=str(self.home / '.gitconfig'))
        for key in list(self.env):
            if key.startswith(('GIT_CONFIG_COUNT', 'GIT_CONFIG_KEY_', 'GIT_CONFIG_VALUE_',
                               'GIT_AUTHOR_', 'GIT_COMMITTER_')):
                self.env.pop(key)
        self.input = self.config / 'local/git/setup-input.gitconfig'
        self.output = self.config / 'local/git/config'
        self.old = self.config / 'local/gitconfig'

    def cli(self, *args, ok=True):
        result = subprocess.run([str(ROOT / 'bin/dotfiles'), *args], env=self.env,
                                cwd=self.home, text=True, capture_output=True, timeout=90)
        if ok:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def install(self, original=None):
        if original is not None:
            (self.home / '.gitconfig').write_text(original)
        self.cli('install', '--profiles', 'shell', '--non-interactive')

    def write_input(self, text, mode=0o600):
        self.input.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.input.write_text(text)
        self.input.chmod(mode)

    def setup_git(self, *args, ok=True):
        return self.cli('git', 'setup', '--non-interactive', *args, ok=ok)

    def git_value(self, key, cwd=None):
        return subprocess.run(['git', 'config', '--includes', '--get', key], env=self.env,
                              cwd=cwd or self.home, text=True, capture_output=True)

    def snapshot(self):
        result = {}
        for path in sorted(self.home.rglob('*')):
            stat = path.lstat()
            content = os.readlink(path) if path.is_symlink() else (
                hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None)
            result[str(path.relative_to(self.home))] = (stat.st_mode, stat.st_mtime_ns, content)
        return result

    def assert_redacted(self, result, *values):
        for value in values:
            self.assertNotIn(value, result.stdout + result.stderr)

    def test_requires_managed_install_and_missing_input_does_not_invent_identity(self):
        self.write_input('[user]\n name = Fixture Setup\n email = setup@example.invalid\n')
        before = self.snapshot()
        self.assertNotEqual(self.setup_git(ok=False).returncode, 0)
        self.assertEqual(before, self.snapshot())
        self.input.unlink()
        self.install()
        before = self.snapshot()
        self.assertNotEqual(self.setup_git(ok=False).returncode, 0)
        self.assertEqual(before, self.snapshot())

    def test_identity_private_permissions_defaults_and_replay(self):
        self.install()
        self.write_input('[user]\n name = Fixture Setup\n email = setup@example.invalid\n')
        result = self.setup_git()
        self.assert_redacted(result, 'Fixture Setup', 'setup@example.invalid')
        self.assertEqual(self.output.stat().st_mode & 0o777, 0o600)
        for key, expected in [('user.name', 'Fixture Setup'), ('user.email', 'setup@example.invalid'),
                              ('user.useConfigOnly', 'true'), ('init.defaultBranch', 'main'),
                              ('pull.ff', 'only'), ('fetch.prune', 'true'), ('push.default', 'simple')]:
            self.assertEqual(self.git_value(key).stdout.strip(), expected)
        content = self.output.read_bytes()
        self.setup_git()
        self.assertEqual(self.output.read_bytes(), content)
        self.cli('repair', '--non-interactive')
        self.assertEqual(self.git_value('user.email').stdout.strip(), 'setup@example.invalid')
        self.cli('uninstall', '--non-interactive')
        self.assertEqual(self.output.read_bytes(), content)

    def test_partial_identity_inherits_old_private_config_and_preserves_credentials(self):
        original = '[user]\n name = Fixture Legacy\n email = legacy@example.invalid\n[credential]\n helper = !printf never-invoke\n'
        self.install(original)
        self.write_input('[user]\n email = replacement@example.invalid\n')
        self.setup_git()
        self.assertEqual(self.old.read_text(), original)
        self.assertEqual(self.git_value('user.name').stdout.strip(), 'Fixture Legacy')
        self.assertEqual(self.git_value('user.email').stdout.strip(), 'replacement@example.invalid')
        self.assertEqual(self.git_value('credential.helper').stdout.strip(), '!printf never-invoke')

    def test_dry_run_and_status_are_read_only_and_redacted(self):
        self.install()
        self.write_input('[user]\n name = Fixture Hidden\n email = hidden@example.invalid\n')
        before = self.snapshot()
        result = self.setup_git('--dry-run')
        self.assertEqual(before, self.snapshot())
        self.assert_redacted(result, 'Fixture Hidden', 'hidden@example.invalid')
        self.assertFalse(self.output.exists())
        self.setup_git()
        before = self.snapshot()
        result = self.cli('git', 'status')
        self.assertEqual(before, self.snapshot())
        self.assert_redacted(result, 'Fixture Hidden', 'hidden@example.invalid')

    def test_forbidden_keys_helpers_and_includes_reject_without_changes(self):
        self.install()
        forbidden = [
            '[alias]\n unsafe = !touch forbidden-marker\n',
            '[credential]\n helper = !touch forbidden-marker\n',
            '[credential]\n helper = store\n',
            '[core]\n sshCommand = touch forbidden-marker\n',
            '[include]\n path = /etc/gitconfig\n',
            '[includeIf "gitdir:/tmp/"]\n path = /etc/gitconfig\n',
            '[user]\n signingkey = -----BEGIN OPENSSH ' + 'PRIVATE KEY-----\n',
        ]
        for body in forbidden:
            with self.subTest(body=body):
                self.write_input('[user]\n name = Fixture Secret\n email = secret@example.invalid\n' + body)
                before = self.snapshot()
                result = self.setup_git(ok=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(before, self.snapshot())
                self.assert_redacted(result, 'Fixture Secret', 'secret@example.invalid', 'forbidden-marker')

    def test_input_permissions_and_symlink_are_rejected(self):
        self.install()
        self.write_input('[user]\n name = Fixture\n email = fixture@example.invalid\n', 0o644)
        before = self.snapshot()
        self.assertNotEqual(self.setup_git(ok=False).returncode, 0)
        self.assertEqual(before, self.snapshot())
        self.input.chmod(0o600)
        destination = self.input.with_name('other.gitconfig')
        self.input.rename(destination)
        self.input.symlink_to(destination)
        before = self.snapshot()
        self.assertNotEqual(self.setup_git(ok=False).returncode, 0)
        self.assertEqual(before, self.snapshot())

    def test_conditional_identity_selects_only_matching_repository(self):
        self.install()
        work = self.home / 'work projects'
        work.mkdir()
        profile = self.input.parent / 'work.gitconfig'
        profile.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        profile.write_text('[user]\n name = Fixture Work\n email = work@example.invalid\n')
        profile.chmod(0o600)
        self.write_input('[user]\n name = Fixture Personal\n email = personal@example.invalid\n'
                         f'[includeIf "gitdir:{work}/"]\n path = "{profile}"\n')
        self.setup_git()
        repo = work / 'project'
        subprocess.run(['git', 'init', str(repo)], env=self.env, capture_output=True, check=True)
        self.assertEqual(self.git_value('user.email', repo).stdout.strip(), 'work@example.invalid')
        self.assertEqual(self.git_value('user.email').stdout.strip(), 'personal@example.invalid')
        def local_git(*args):
            return subprocess.run(['git', '-c', 'core.hooksPath=/dev/null',
                                   '-c', 'commit.gpgsign=false', '-C', str(repo), *args],
                                  env=self.env, text=True, capture_output=True, check=True)
        local_git('commit', '--allow-empty', '-m', 'fixture worktree base')
        linked = self.home / 'outside profile root'
        local_git('worktree', 'add', '--detach', str(linked))
        self.assertFalse(linked.is_relative_to(work))
        self.assertEqual(self.git_value('user.email', linked).stdout.strip(), 'work@example.invalid')


    def test_profile_forbidden_command_and_symlink_rejected(self):
        self.install()
        profile = self.input.parent / 'work.gitconfig'
        profile.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        profile.write_text('[alias]\n bad = !touch forbidden-profile-marker\n')
        profile.chmod(0o600)
        self.write_input(f'[includeIf "gitdir:{self.home}/work/"]\n path = "{profile}"\n')
        before = self.snapshot()
        self.assertNotEqual(self.setup_git(ok=False).returncode, 0)
        self.assertEqual(before, self.snapshot())
        profile.unlink()
        profile.symlink_to(self.old)
        before = self.snapshot()
        self.assertNotEqual(self.setup_git(ok=False).returncode, 0)
        self.assertEqual(before, self.snapshot())

    def test_ssh_public_key_enables_signing_without_changing_key(self):
        executable = shutil.which('ssh-keygen')
        if not executable:
            self.skipTest('ssh-keygen unavailable')
        self.install()
        key = self.home / 'fixture signing key'
        subprocess.run([executable, '-q', '-t', 'ed25519', '-N', '', '-C', 'fixture-only', '-f', str(key)],
                       env=self.env, capture_output=True, check=True)
        before_key = (key.read_bytes(), key.with_suffix('.pub').read_bytes())
        self.write_input(f'[user]\n name = Fixture Signer\n email = signer@example.invalid\n signingkey = "{key}.pub"\n'
                         '[gpg]\n format = ssh\n[commit]\n gpgsign = true\n[tag]\n gpgsign = true\n')
        result = self.setup_git()
        self.assert_redacted(result, 'signer@example.invalid', before_key[1].decode().strip())
        self.assertEqual(self.git_value('gpg.format').stdout.strip(), 'ssh')
        self.assertEqual(self.git_value('commit.gpgsign').stdout.strip(), 'true')
        self.assertEqual(before_key, (key.read_bytes(), key.with_suffix('.pub').read_bytes()))
        repository = self.home / 'signed repository'
        subprocess.run(['git', 'init', str(repository)], env=self.env, capture_output=True, check=True)
        signed = subprocess.run(['git', '-C', str(repository), 'commit', '--allow-empty', '-m', 'Fixture signed'],
                                env=self.env, capture_output=True, text=True)
        self.assertEqual(signed.returncode, 0, signed.stderr)
        signature = subprocess.check_output(['git', '-C', str(repository), 'cat-file', 'commit', 'HEAD'], env=self.env, text=True)
        self.assertIn('gpgsig -----BEGIN SSH SIGNATURE-----', signature)

    def test_enabled_signing_missing_key_rejects_atomically(self):
        self.install()
        self.write_input('[user]\n name = Fixture Signer\n email = signer@example.invalid\n signingkey = missing-fixture-key.pub\n'
                         '[gpg]\n format = ssh\n[commit]\n gpgsign = true\n')
        before = self.snapshot()
        result = self.setup_git(ok=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(before, self.snapshot())
        self.assert_redacted(result, 'signer@example.invalid', 'missing-fixture-key.pub')

    def test_available_secure_helper_is_configured_without_execution(self):
        self.install()
        mock_bin = self.home / 'mock-bin'
        mock_bin.mkdir()
        helper = mock_bin / 'git-credential-manager'
        marker = self.home / 'helper-must-not-run'
        helper.write_text('#!/bin/sh\ntouch "$HOME/helper-must-not-run"\nexit 91\n')
        helper.chmod(0o755)
        self.env['PATH'] = str(mock_bin) + os.pathsep + self.env['PATH']
        self.write_input('[user]\n name = Fixture Helper\n email = helper@example.invalid\n'
                         '[credential]\n helper = manager\n')
        self.setup_git()
        self.assertFalse(marker.exists())
        self.assertEqual(self.git_value('credential.helper').stdout.strip(), 'manager')

    def test_missing_secure_helper_is_refused_without_installation(self):
        self.install()
        mock_bin = self.home / 'limited-bin'
        mock_bin.mkdir()
        for executable in ('sh', 'dirname', 'git', 'python3', 'uname', 'id', 'stat',
                           'mkdir', 'chmod', 'date', 'ps', 'hostname', 'awk', 'sed',
                           'cat', 'mv', 'rm', 'rmdir', 'mktemp', 'tr', 'wc', 'od',
                           'head', 'cut', 'sort', 'find', 'cp', 'readlink', 'basename'):
            real = shutil.which(executable)
            if real:
                (mock_bin / executable).symlink_to(real)
        self.env['PATH'] = str(mock_bin)
        self.write_input('[user]\n name = Fixture Helper\n email = helper@example.invalid\n'
                         '[credential]\n helper = libsecret\n')
        before = self.snapshot()
        self.assertNotEqual(self.setup_git(ok=False).returncode, 0)
        self.assertEqual(before, self.snapshot())

    def test_profile_permissions_and_external_reference_are_refused(self):
        self.install()
        profile = self.home / 'unsafe-profile.gitconfig'
        profile.write_text('[user]\n email = profile@example.invalid\n')
        profile.chmod(0o644)
        self.write_input(f'[includeIf "gitdir:{self.home}/work/"]\n path = "{profile}"\n')
        before = self.snapshot()
        result = self.setup_git(ok=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(before, self.snapshot())
        self.assert_redacted(result, 'profile@example.invalid')

    def test_private_ssh_key_reference_refused_and_existing_ssh_configuration_preserved(self):
        self.install()
        ssh_dir = self.home / '.ssh'
        ssh_dir.mkdir(mode=0o700)
        ssh_config = ssh_dir / 'config'
        ssh_config.write_text('Host fixture\n  HostName host.example.invalid\n')
        ssh_config.chmod(0o600)
        key = ssh_dir / 'id_fixture'
        key.write_text('-----BEGIN OPENSSH ' + 'PRIVATE KEY-----\nfixture-invalid\n')
        key.chmod(0o600)
        self.write_input(f'[user]\n name = Fixture Signer\n email = signer@example.invalid\n signingkey = "{key}"\n'
                         '[gpg]\n format = ssh\n[commit]\n gpgsign = true\n')
        before = self.snapshot()
        result = self.setup_git(ok=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(before, self.snapshot())
        self.assert_redacted(result, 'signer@example.invalid', 'host.example.invalid', 'fixture-invalid')

    def test_interactive_terminal_identity_and_signing_choices(self):
        self.install()
        environment = dict(self.env, DOTFILES_MODE='non-interactive')
        child, terminal = pty.fork()
        if child == 0:
            os.chdir(self.home)
            os.execve(str(ROOT / 'bin/dotfiles'),
                      [str(ROOT / 'bin/dotfiles'), 'git', 'setup'], environment)
        prompts = [('Change global identity?', 'y'), ('Git name:', 'Fixture Terminal'),
                   ('Git email:', 'terminal@example.invalid'), ('Change HTTPS helper?', 'n'),
                   ('Signing:', 'off'), ('Add a private directory identity profile?', 'n'),
                   ('Apply these private choices?', 'y')]
        output = b''
        deadline = time.monotonic() + 35
        status = None
        reaped = False
        try:
            while time.monotonic() < deadline:
                ready, _, _ = select.select([terminal], [], [], 0.1)
                if ready:
                    try:
                        block = os.read(terminal, 65536)
                    except OSError:
                        block = b''
                    output += block
                    if prompts and prompts[0][0].encode() in output:
                        os.write(terminal, (prompts.pop(0)[1] + '\n').encode())
                        output = b''
                waited, status = os.waitpid(child, os.WNOHANG)
                if waited:
                    reaped = True
                    break
            else:
                self.fail('Interactive Git setup did not complete its terminal dialogue')
            self.assertFalse(prompts, 'Interactive dialogue ended before all choices')
            self.assertTrue(os.WIFEXITED(status))
            self.assertEqual(os.WEXITSTATUS(status), 0)
        finally:
            os.close(terminal)
            if not reaped:
                try:
                    os.kill(child, signal.SIGKILL)
                    os.waitpid(child, 0)
                except ProcessLookupError:
                    pass
        self.assertEqual(self.git_value('user.email').stdout.strip(), 'terminal@example.invalid')
        self.assertEqual(self.git_value('commit.gpgsign').stdout.strip(), 'false')

    def test_custom_private_configuration_location(self):
        self.config = self.home / 'alternate configuration/dotfiles'
        self.env['DOTFILES_CONFIG'] = str(self.config)
        self.input = self.config / 'local/git/setup-input.gitconfig'
        self.output = self.config / 'local/git/config'
        self.install()
        self.write_input('[user]\n name = Fixture Alternate\n email = alternate@example.invalid\n')
        self.setup_git()
        self.assertEqual(self.git_value('user.email').stdout.strip(), 'alternate@example.invalid')

    def test_global_override_cannot_silently_bypass_private_setup(self):
        self.install()
        self.write_input('[user]\n name = Fixture Override\n email = override@example.invalid\n')
        alternate = self.home / 'unmanaged-global'
        alternate.write_text('[user]\n email = existing@example.invalid\n')
        self.env['GIT_CONFIG_GLOBAL'] = str(alternate)
        before = self.snapshot()
        result = self.setup_git(ok=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(before, self.snapshot())
        self.assert_redacted(result, str(alternate), 'existing@example.invalid', 'override@example.invalid')

    def test_diverged_pull_refuses_and_preserves_local_commit(self):
        self.install()
        self.write_input('[user]\n name = Fixture Pull\n email = pull@example.invalid\n')
        self.setup_git()
        remote = self.home / 'remote.git'
        seed = self.home / 'seed'
        clone = self.home / 'clone'
        def local_git(directory, *args, check=True):
            return subprocess.run(['git', '-c', 'core.hooksPath=/dev/null',
                                   '-c', 'commit.gpgsign=false', '-C', str(directory), *args],
                                  env=self.env, text=True, capture_output=True, check=check, timeout=15)
        local_git(self.home, 'init', '--bare', str(remote))
        local_git(self.home, 'init', str(seed))
        (seed / 'base').write_text('fixture base\n')
        local_git(seed, 'add', 'base')
        local_git(seed, 'commit', '-m', 'fixture base')
        local_git(seed, 'remote', 'add', 'origin', str(remote))
        local_git(seed, 'push', '-u', 'origin', 'main')
        local_git(self.home, 'clone', str(remote), str(clone))
        (clone / 'local-only').write_text('preserve local fixture\n')
        local_git(clone, 'add', 'local-only')
        local_git(clone, 'commit', '-m', 'fixture local divergence')
        before_head = local_git(clone, 'rev-parse', 'HEAD').stdout
        (seed / 'remote-only').write_text('fixture remote divergence\n')
        local_git(seed, 'add', 'remote-only')
        local_git(seed, 'commit', '-m', 'fixture remote divergence')
        local_git(seed, 'push', 'origin', 'main')
        result = local_git(clone, 'pull', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(local_git(clone, 'rev-parse', 'HEAD').stdout, before_head)
        self.assertEqual((clone / 'local-only').read_text(), 'preserve local fixture\n')
        self.assertFalse((clone / 'remote-only').exists())
        self.assertEqual(local_git(clone, 'status', '--porcelain').stdout, '')
        self.assertFalse((clone / '.git/MERGE_HEAD').exists())
