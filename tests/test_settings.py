import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_REPOSITORY = 'https://github.com/phcorp/dotfiles.git'


class Settings(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='dotfiles-settings-')
        self.addCleanup(self.tmp.cleanup)
        self.home = pathlib.Path(self.tmp.name)
        self.config = self.home / 'config'
        self.config.mkdir(mode=0o700)
        self.settings = self.config / 'settings'
        self.source = self.home / 'source'
        self.git_config = self.home / 'gitconfig'
        self.env = dict(os.environ, HOME=str(self.home), DOTFILES_CONFIG=str(self.config),
                        DOTFILES_SOURCE=str(self.source), GIT_CONFIG_GLOBAL=str(self.git_config),
                        GIT_CONFIG_NOSYSTEM='1')
        for key in ['DOTFILES_REPOSITORY', 'DOTFILES_BRANCH', 'DOTFILES_PUBLISH_NAME',
                    'DOTFILES_PUBLISH_EMAIL', 'DOTFILES_TESTING', 'DOTFILES_SYNC_SKIP_CI']:
            self.env.pop(key, None)
        self.git('init', str(self.source))
        self.git('-C', str(self.source), 'remote', 'add', 'origin', DEFAULT_REPOSITORY)

    def git(self, *args):
        return subprocess.run(['git', *args], env=self.env, capture_output=True, text=True, check=True)

    def write(self, body, mode=0o600):
        self.settings.write_text(body)
        self.settings.chmod(mode)

    def run_shell(self, body):
        return subprocess.run(['/bin/sh', '-c', '. "$1"; ' + body, 'settings-test',
                               str(ROOT / 'lib/settings.sh')], env=self.env,
                              capture_output=True, text=True, timeout=10)

    def test_defaults_without_writing_files(self):
        result = self.run_shell('settings_load && printf "%s\\n" "$DOTFILES_REPOSITORY" "$DOTFILES_BRANCH" "$DOTFILES_PUBLISH_NAME" "$DOTFILES_PUBLISH_EMAIL"')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), [DEFAULT_REPOSITORY, 'master', 'phcorp', '725023+phcorp@users.noreply.github.com'])
        self.assertFalse(self.settings.exists())

    def test_literal_private_values_and_environment_precedence(self):
        self.write('''# Private machine choices
DOTFILES_REPOSITORY=git@github.com:team/config.git
DOTFILES_BRANCH=release/private
DOTFILES_PUBLISH_NAME=public-alias
DOTFILES_PUBLISH_EMAIL=12345+public-alias@users.noreply.github.com''')
        self.env['DOTFILES_BRANCH'] = 'release/environment'
        result = self.run_shell('settings_load && printf "%s\\n" "$DOTFILES_REPOSITORY" "$DOTFILES_BRANCH" "$DOTFILES_PUBLISH_NAME"')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ['git@github.com:team/config.git', 'release/environment', 'public-alias'])

    def test_explicit_empty_environment_does_not_fall_back(self):
        self.env['DOTFILES_BRANCH'] = ''
        result = self.run_shell('settings_load')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, '')

    def test_invalid_values_are_redacted(self):
        values = [
            'DOTFILES_REPOSITORY=https://private-secret@github.com/team/config.git\n',
            'DOTFILES_REPOSITORY=https://example.invalid/team/config\n',
            'DOTFILES_REPOSITORY=https://github.com/team/..\n',
            'DOTFILES_BRANCH=branch with spaces\n',
            'DOTFILES_PUBLISH_NAME=Private Person\nDOTFILES_PUBLISH_EMAIL=private@example.invalid\n',
            'DOTFILES_PUBLISH_NAME=other-alias\n',
            'DOTFILES_PUBLISH_EMAIL=other-alias@users.noreply.github.com\n',
            'DOTFILES_PUBLISH_EMAIL=abc+phcorp@users.noreply.github.com\n',
        ]
        for value in values:
            with self.subTest(value=value):
                self.write(value)
                result = self.run_shell('settings_load')
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, '')
                self.assertNotIn('private-secret', result.stderr)
                self.assertNotIn('Private Person', result.stderr)
                self.assertNotIn('private@example.invalid', result.stderr)

    def test_unknown_duplicate_or_nonliteral_lines_fail(self):
        for body in ['OTHER=value\n', 'export DOTFILES_BRANCH=master\n', 'DOTFILES_BRANCH=master\nDOTFILES_BRANCH=other\n', 'not-an-assignment\n']:
            with self.subTest(body=body):
                self.write(body)
                self.assertNotEqual(self.run_shell('settings_load').returncode, 0)

    def test_shell_expressions_never_execute(self):
        marker = self.home / 'must-not-exist'
        self.write('DOTFILES_BRANCH=$(touch ' + str(marker) + ')\n')
        self.assertNotEqual(self.run_shell('settings_load').returncode, 0)
        self.assertFalse(marker.exists())
        self.write('DOTFILES_BRANCH=`touch ' + str(marker) + '`\n')
        self.assertNotEqual(self.run_shell('settings_load').returncode, 0)
        self.assertFalse(marker.exists())

    def test_permission_and_symlink_boundaries(self):
        self.write('DOTFILES_BRANCH=master\n', mode=0o644)
        self.assertNotEqual(self.run_shell('settings_load').returncode, 0)
        self.settings.chmod(0o400)
        self.assertEqual(self.run_shell('settings_load').returncode, 0)
        self.settings.unlink()
        self.settings.symlink_to(self.git_config)
        self.assertNotEqual(self.run_shell('settings_load').returncode, 0)

    def test_settings_directory_cannot_escape_home(self):
        with tempfile.TemporaryDirectory(prefix='dotfiles-settings-outside-') as directory:
            outside = pathlib.Path(directory)
            (outside / 'settings').write_text('DOTFILES_BRANCH=master\n')
            (outside / 'settings').chmod(0o600)
            link = self.home / 'escaped'
            link.symlink_to(outside, target_is_directory=True)
            self.env['DOTFILES_CONFIG'] = str(link)
            self.assertNotEqual(self.run_shell('settings_load').returncode, 0)

    def test_matching_fetch_and_push_origin(self):
        self.assertEqual(self.run_shell('settings_load && settings_check_origin').returncode, 0)
        self.git('-C', str(self.source), 'remote', 'set-url', 'origin', 'git@github.com:PhCorp/Dotfiles.git')
        self.assertEqual(self.run_shell('settings_load && settings_check_origin').returncode, 0)

    def test_mismatched_fetch_or_push_origins_are_rejected(self):
        self.git('-C', str(self.source), 'remote', 'set-url', '--push', 'origin', 'https://github.com/other/repo.git')
        self.assertNotEqual(self.run_shell('settings_load && settings_check_origin').returncode, 0)
        self.git('-C', str(self.source), 'config', '--unset-all', 'remote.origin.pushurl')
        self.git('-C', str(self.source), 'remote', 'set-url', 'origin', 'https://github.com/other/repo.git')
        self.assertNotEqual(self.run_shell('settings_load && settings_check_origin').returncode, 0)

    def test_effective_git_rewrites_are_checked(self):
        self.git('config', '--file', str(self.git_config), 'url.https://github.com/other/repo.git.insteadOf', DEFAULT_REPOSITORY)
        self.assertNotEqual(self.run_shell('settings_load && settings_check_origin').returncode, 0)

    def test_extra_origin_urls_are_checked(self):
        self.git('-C', str(self.source), 'remote', 'set-url', '--add', 'origin', 'https://github.com/other/repo.git')
        self.assertNotEqual(self.run_shell('settings_load && settings_check_origin').returncode, 0)

    def test_local_fixture_requires_both_test_flags(self):
        self.git('-C', str(self.source), 'remote', 'set-url', 'origin', str(self.home / 'fixture'))
        for testing, bypass, succeeds in [('0', '0', False), ('1', '0', False), ('0', '1', False), ('1', '1', True)]:
            with self.subTest(testing=testing, bypass=bypass):
                self.env.update(DOTFILES_TESTING=testing, DOTFILES_SYNC_SKIP_CI=bypass)
                self.assertEqual(self.run_shell('settings_load && settings_check_origin').returncode == 0, succeeds)
        self.git('-C', str(self.source), 'remote', 'set-url', 'origin', 'https://github.com/other/repo.git')
        self.assertNotEqual(self.run_shell('settings_load && settings_check_origin').returncode, 0)

    def test_loading_never_rewrites_private_git_identity(self):
        self.git('-C', str(self.source), 'config', 'user.name', 'Private Fixture')
        self.git('-C', str(self.source), 'config', 'user.email', 'private@example.invalid')
        before = (self.source / '.git/config').read_bytes()
        self.env['GIT_AUTHOR_NAME'] = 'Private Environment'
        result = self.run_shell('settings_load && printf "%s" "$GIT_AUTHOR_NAME"')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'Private Environment')
        self.assertEqual(before, (self.source / '.git/config').read_bytes())

    def test_publication_sets_only_process_metadata(self):
        before = (self.source / '.git/config').read_bytes()
        self.env.update(DOTFILES_PUBLISH_NAME='maintainer-alias',
                        DOTFILES_PUBLISH_EMAIL='54321+maintainer-alias@users.noreply.github.com')
        result = self.run_shell('settings_load && settings_publish_git_env && printf "%s\\n" "$GIT_AUTHOR_NAME" "$GIT_AUTHOR_EMAIL" "$GIT_COMMITTER_NAME" "$GIT_COMMITTER_EMAIL"')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ['maintainer-alias', '54321+maintainer-alias@users.noreply.github.com'] * 2)
        self.assertEqual(before, (self.source / '.git/config').read_bytes())


@unittest.skipUnless(shutil.which('chezmoi'), 'chezmoi is required for isolated CLI integration')
class SettingsCLIIntegration(unittest.TestCase):
    """Apply only to disposable HOME; Git transports are local fixture directories."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='dotfiles-settings-cli-')
        self.addCleanup(self.tmp.cleanup)
        self.base = pathlib.Path(self.tmp.name)
        self.home = self.base / 'home'
        self.home.mkdir()
        self.seed = self.base / 'seed'
        shutil.copytree(ROOT, self.seed, ignore=shutil.ignore_patterns('.git', '__pycache__'))
        self.git_env = dict(os.environ, GIT_CONFIG_GLOBAL=str(self.base / 'empty-gitconfig'),
                            GIT_CONFIG_NOSYSTEM='1', GIT_AUTHOR_NAME='fixture',
                            GIT_COMMITTER_NAME='fixture',
                            GIT_AUTHOR_EMAIL='fixture@users.noreply.github.com',
                            GIT_COMMITTER_EMAIL='fixture@users.noreply.github.com')
        self.git(self.seed, 'init', '-b', 'master')
        self.git(self.seed, 'add', '.')
        self.git(self.seed, 'commit', '-m', 'settings fixture')
        self.git(self.seed, 'branch', 'release/configured')
        self.remote = self.base / 'remote.git'
        self.git(self.base, 'clone', '--bare', str(self.seed), str(self.remote))
        self.source = self.base / 'source'
        self.git(self.base, 'clone', str(self.remote), str(self.source))
        self.config = self.home / '.config/dotfiles'
        self.env = dict(self.git_env, HOME=str(self.home), DOTFILES_SOURCE=str(self.source),
                        DOTFILES_CONFIG=str(self.config),
                        DOTFILES_STATE=str(self.home / '.local/state/dotfiles'),
                        XDG_CONFIG_HOME=str(self.home / '.config'),
                        XDG_STATE_HOME=str(self.home / '.local/state'),
                        XDG_DATA_HOME=str(self.home / '.local/share'),
                        DOTFILES_MODE='non-interactive')
        for key in ['DOTFILES_REPOSITORY', 'DOTFILES_BRANCH', 'DOTFILES_PUBLISH_NAME',
                    'DOTFILES_PUBLISH_EMAIL', 'DOTFILES_TESTING', 'DOTFILES_SYNC_SKIP_CI']:
            self.env.pop(key, None)

    def git(self, cwd, *args):
        result = subprocess.run(['git', '-c', 'core.hooksPath=/dev/null', '-C', str(cwd), *args],
                                env=self.git_env, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def cli(self, *args):
        result = subprocess.run([str(self.source / 'bin/dotfiles'), *args], env=self.env,
                                cwd=self.home, capture_output=True, text=True, timeout=90)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def test_cli_install_preserves_existing_source_git_identity(self):
        # Do not set DOTFILES_TESTING: cover the actual install integration path.
        self.git(self.source, 'config', 'user.name', 'Private Fixture')
        self.git(self.source, 'config', 'user.email', 'private-fixture@example.invalid')
        self.cli('install', '--non-interactive', '--profiles', 'shell')
        self.assertEqual(self.git(self.source, 'config', '--get', 'user.name'), 'Private Fixture')
        self.assertEqual(self.git(self.source, 'config', '--get', 'user.email'), 'private-fixture@example.invalid')
        self.assertTrue((self.home / '.bashrc').exists())

    def test_cli_sync_uses_private_configured_non_master_branch(self):
        self.env.update(DOTFILES_TESTING='1', DOTFILES_SYNC_SKIP_CI='1')
        self.git(self.source, 'checkout', 'release/configured')
        self.config.mkdir(parents=True, mode=0o700)
        settings = self.config / 'settings'
        settings.write_text('DOTFILES_BRANCH=release/configured\n')
        settings.chmod(0o600)
        self.cli('install', '--non-interactive', '--profiles', 'shell')
        original_master = self.git(self.remote, 'rev-parse', 'refs/heads/master')
        upstream = self.base / 'upstream'
        self.git(self.base, 'clone', '--branch', 'release/configured', str(self.remote), str(upstream))
        target = upstream / 'home/dot_inputrc'
        target.write_text(target.read_text() + '\n# configured branch fixture\n')
        self.git(upstream, 'add', 'home/dot_inputrc')
        self.git(upstream, 'commit', '-m', 'configured branch change')
        # Populate only the local bare fixture, without any push or network access.
        self.git(self.remote, 'fetch', '--no-tags', str(upstream), 'HEAD:refs/heads/release/configured')
        wanted = self.git(self.remote, 'rev-parse', 'refs/heads/release/configured')
        self.cli('sync', '--non-interactive')
        self.assertEqual(self.git(self.source, 'rev-parse', 'HEAD'), wanted)
        self.assertEqual(self.git(self.remote, 'rev-parse', 'refs/heads/master'), original_master)
        self.assertIn('# configured branch fixture', (self.home / '.inputrc').read_text())
