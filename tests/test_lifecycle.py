"""Behavior checks use disposable homes and never invoke real package installation."""
import os
import pathlib
import shutil
import sys
import shlex
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class Lifecycle(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='dotfiles-test-')
        self.addCleanup(self.tmp.cleanup)
        self.home = pathlib.Path(self.tmp.name) / 'home with spaces'
        self.home.mkdir()
        self.env = dict(os.environ, HOME=str(self.home),
                        XDG_CONFIG_HOME=str(self.home / '.config'),
                        XDG_STATE_HOME=str(self.home / '.local/state'),
                        XDG_CACHE_HOME=str(self.home / '.cache'),
                        DOTFILES_SOURCE=str(ROOT),
                        DOTFILES_CONFIG=str(self.home / '.config/dotfiles'),
                        DOTFILES_STATE=str(self.home / '.local/state/dotfiles'),
                        DOTFILES_MODE='non-interactive', DOTFILES_TESTING='1')

    def run_cli(self, *args, check=True):
        result = subprocess.run([str(ROOT / 'bin/dotfiles'), *args], env=self.env,
                                cwd=self.home, text=True, capture_output=True, timeout=90)
        if check:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def install(self):
        return self.run_cli('install', '--non-interactive', '--profiles', 'shell')

    def test_dry_run_does_not_change_home(self):
        before = sorted(p.relative_to(self.home) for p in self.home.rglob('*'))
        self.run_cli('install', '--non-interactive', '--dry-run', '--profiles', 'shell')
        after = sorted(p.relative_to(self.home) for p in self.home.rglob('*'))
        self.assertEqual(before, after)

    def test_install_repeat_restore_and_private_git(self):
        original = '# existing bash config\n'
        (self.home / '.bashrc').write_text(original)
        gitconfig = '[user]\n    name = Test Person\n    email = person@example.invalid\n[credential]\n    helper = test-helper\n'
        (self.home / '.gitconfig').write_text(gitconfig)
        self.install()
        configured = (self.home / '.bashrc').read_text()
        self.assertNotEqual(configured, original)
        self.install()
        self.assertEqual((self.home / '.bashrc').read_text(), configured)
        private = self.home / '.config/dotfiles/local/gitconfig'
        self.assertEqual(private.read_text(), gitconfig)
        self.assertEqual(private.stat().st_mode & 0o077, 0)
        self.run_cli('uninstall', '--non-interactive')
        self.assertEqual((self.home / '.bashrc').read_text(), original)
        self.assertTrue(private.exists())

    def test_local_edit_is_preserved(self):
        self.install()
        target = self.home / '.bashrc'
        edited = target.read_text() + '\n# personal edit\n'
        target.write_text(edited)
        result = self.run_cli('repair', '--non-interactive', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(target.read_text(), edited)
        result = self.run_cli('uninstall', '--non-interactive', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(target.read_text(), edited)

    def test_noninteractive_shells_are_silent(self):
        self.install()
        for shell in ('bash', 'zsh'):
            executable = '/bin/bash' if shell == 'bash' and sys.platform == 'darwin' else shutil.which(shell)
            if not executable:
                continue
            result = subprocess.run([executable, '-c', 'printf shell-ok'],
                                    env=self.env, cwd=self.home,
                                    text=True, capture_output=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, 'shell-ok')
            self.assertEqual(result.stderr, '')

    def test_interactive_startup_without_optional_tools(self):
        self.install()
        (self.home / '.config/dotfiles/local/env.sh').write_text('PATH=/usr/bin:/bin\nexport PATH\n')
        environment = dict(self.env, PATH='/usr/bin:/bin', TERM='dumb')
        for shell in ('bash', 'zsh'):
            executable = '/bin/bash' if shell == 'bash' and sys.platform == 'darwin' else shutil.which(shell)
            if not executable:
                continue
            args = [executable, '-ic', 'printf shell-ok']
            result = subprocess.run(args, env=environment, cwd=self.home,
                                    capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, 'shell-ok')
            errors = [line for line in result.stderr.splitlines()
                      if 'cannot set terminal process group' not in line
                      and 'no job control in this shell' not in line]
            self.assertEqual(errors, [])

    def test_first_use_retries_and_preserves_arguments_and_status(self):
        self.install()
        fixture_bin = self.home / 'fixture-bin'
        fixture_bin.mkdir()
        (self.home / '.config/dotfiles/local/env.sh').write_text(
            'PATH="$HOME/fixture-bin:/usr/bin:/bin"\nexport PATH\n')
        installer = fixture_bin / 'dotfiles'
        installer.write_text("""#!/bin/sh
[ "$1 $2 $3" = 'tools ensure symfony' ] || exit 71
cat > "$HOME/fixture-bin/symfony" <<'SCRIPT'
#!/bin/sh
printf '%s\n' "$@"
exit 23
SCRIPT
chmod +x "$HOME/fixture-bin/symfony"
""")
        installer.chmod(0o755)
        for shell in ('bash', 'zsh'):
            executable = '/bin/bash' if shell == 'bash' and sys.platform == 'darwin' else shutil.which(shell)
            if not executable:
                continue
            tool = fixture_bin / 'symfony'
            if tool.exists():
                tool.unlink()
            result = subprocess.run([executable, '-ic', "symfony 'two words' '*' --flag"],
                                    env=dict(self.env, TERM='dumb'), cwd=self.home,
                                    capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 23, result.stderr)
            self.assertEqual(result.stdout, 'two words\n*\n--flag\n')
            self.assertTrue(tool.exists())

    def test_relocated_xdg_configuration(self):
        config = self.home / 'alternate config'
        state = self.home / 'alternate state'
        self.env.update(XDG_CONFIG_HOME=str(config), XDG_STATE_HOME=str(state),
                        DOTFILES_CONFIG=str(config / 'dotfiles'), DOTFILES_STATE=str(state / 'dotfiles'))
        (self.home / '.gitconfig').write_text('[user]\n    name = Fixture\n')
        self.install()
        self.assertTrue((config / 'dotfiles/env.sh').is_file())
        self.assertTrue((config / 'dotfiles/local/gitconfig').is_file())
        self.assertFalse((self.home / '.config/dotfiles/env.sh').exists())
        result = subprocess.run(['git', 'config', '--global', '--includes', '--get', 'user.name'],
                                env=self.env, text=True, capture_output=True)
        self.assertEqual(result.stdout.strip(), 'Fixture')
        self.run_cli('uninstall', '--non-interactive')
        self.assertFalse((config / 'dotfiles/env.sh').exists())
        self.assertTrue((config / 'dotfiles/local/gitconfig').exists())

    def test_interrupted_transaction_recovers(self):
        self.install()
        target = self.home / '.bashrc'
        previous = target.read_text()
        transaction = self.home / '.local/state/dotfiles/transaction'
        (transaction / 'files').mkdir(parents=True)
        (transaction / 'files/.bashrc').write_text(previous)
        (transaction / 'paths').write_text(str(target) + '\n')
        target.write_text('interrupted replacement\n')
        self.run_cli('recover', '--non-interactive')
        self.assertEqual(target.read_text(), previous)
        self.assertFalse(transaction.exists())

    def test_symlink_ancestor_outside_home_is_rejected(self):
        outside = pathlib.Path(self.tmp.name) / 'outside'
        outside.mkdir()
        (outside / 'sentinel').write_text('preserve\n')
        (self.home / '.config').mkdir()
        (self.home / '.config/dotfiles').symlink_to(outside, target_is_directory=True)
        result = self.run_cli('install', '--non-interactive', '--profiles', 'shell', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(sorted(p.name for p in outside.iterdir()), ['sentinel'])
        self.assertEqual((outside / 'sentinel').read_text(), 'preserve\n')

    def test_private_directory_symlink_leaves_are_rejected(self):
        outside = pathlib.Path(self.tmp.name) / 'outside'
        outside.mkdir()
        for relative in ('.config/dotfiles/local', '.local/state/dotfiles/originals'):
            with self.subTest(path=relative):
                target = self.home / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.symlink_to(outside, target_is_directory=True)
                result = self.run_cli('install', '--non-interactive', '--profiles', 'shell', check=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(list(outside.iterdir()), [])
                target.unlink()

    def test_uninstall_refuses_changed_config_ancestor(self):
        self.install()
        config = self.home / '.config'
        config.rename(self.home / '.config.saved')
        outside = pathlib.Path(self.tmp.name) / 'outside'
        outside.mkdir()
        config.symlink_to(outside, target_is_directory=True)
        result = self.run_cli('uninstall', '--non-interactive', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(list(outside.iterdir()), [])

    def test_failed_command_link_rolls_back_apply(self):
        original = '# original config\n'
        (self.home / '.bashrc').write_text(original)
        fake_bin = self.home / 'fixture-bin'
        fake_bin.mkdir()
        script = fake_bin / 'ln'
        script.write_text('#!/bin/sh\nexit 7\n')
        script.chmod(0o755)
        self.env['PATH'] = str(fake_bin) + ':' + self.env['PATH']
        result = self.run_cli('install', '--non-interactive', '--profiles', 'shell', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.home / '.bashrc').read_text(), original)
        self.assertFalse((self.home / '.local/state/dotfiles/transaction').exists())

    def test_failed_managed_manifest_aborts_before_apply(self):
        original = '# original config\n'
        (self.home / '.bashrc').write_text(original)
        fake_bin = self.home / 'fixture-bin'
        fake_bin.mkdir()
        executable = shutil.which('chezmoi')
        self.assertIsNotNone(executable)
        script = fake_bin / 'chezmoi'
        script.write_text('#!/bin/sh\nfor arg do [ "$arg" != managed ] || exit 31; done\nexec ' +
                          shlex.quote(executable) + ' "$@"\n')
        script.chmod(0o755)
        self.env['PATH'] = str(fake_bin) + ':' + self.env['PATH']
        result = self.run_cli('install', '--non-interactive', '--profiles', 'shell', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.home / '.bashrc').read_text(), original)

    def test_git_identity_survives(self):
        (self.home / '.gitconfig').write_text('[user]\n    name = Fixture User\n    email = fixture@example.invalid\n')
        self.install()
        for key, value in [('user.name', 'Fixture User'), ('user.email', 'fixture@example.invalid')]:
            result = subprocess.run(['git', 'config', '--global', '--includes', '--get', key],
                                    env=self.env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), value)


if __name__ == '__main__':
    unittest.main()
