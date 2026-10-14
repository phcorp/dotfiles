import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
REPOSITORY = 'https://github.com/phcorp/dotfiles.git'


@unittest.skipUnless(shutil.which('jq'), 'jq is required')
class BootstrapTrust(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='dotfiles-bootstrap-')
        self.addCleanup(self.tmp.cleanup)
        self.home = pathlib.Path(self.tmp.name)
        self.remote = self.home / 'fixture-remote'
        self.source = self.home / 'source'
        self.bin = self.home / 'fixtures'
        self.bin.mkdir()
        self.marker = self.home / 'executed.json'
        self.api_log = self.home / 'api-called'
        self.config = self.home / 'gitconfig'
        self.env = dict(os.environ, HOME=str(self.home), XDG_DATA_HOME=str(self.home / 'data'),
                        DOTFILES_SOURCE=str(self.source), DOTFILES_REPOSITORY=REPOSITORY,
                        DOTFILES_BRANCH='master', GIT_CONFIG_GLOBAL=str(self.config),
                        GIT_CONFIG_NOSYSTEM='1', EXECUTION_MARKER=str(self.marker),
                        API_LOG=str(self.api_log), PATH=str(self.bin) + ':' + os.environ['PATH'])
        self.env.pop('GITHUB_TOKEN', None)
        self.git('init', '--initial-branch=master', str(self.remote))
        (self.remote / 'bin').mkdir()
        (self.remote / 'bin/dotfiles').write_text(f'#!{sys.executable}\n' + '''import json, os, subprocess, pathlib, sys
sha = subprocess.check_output(['git', '-C', os.environ['DOTFILES_SOURCE'], 'rev-parse', 'HEAD'], text=True).strip()
pathlib.Path(os.environ['EXECUTION_MARKER']).write_text(json.dumps({'sha': sha, 'args': sys.argv[1:]}))
''')
        (self.remote / 'bin/dotfiles').chmod(0o755)
        self.git('-C', str(self.remote), 'add', '.')
        self.git('-C', str(self.remote), '-c', 'user.name=Fixture', '-c', 'user.email=fixture@users.noreply.github.com', 'commit', '-m', 'Fixture')
        self.sha = self.git('-C', str(self.remote), 'rev-parse', 'HEAD').stdout.strip()
        self.git('config', '--file', str(self.config), f'url.{self.remote}.insteadOf', REPOSITORY)
        self.script('uname', '#!/bin/sh\ncase $1 in -s) echo Linux ;; -m) echo x86_64 ;; esac\n')
        self.script('chezmoi', '#!/bin/sh\nexit 0\n')
        self.script('curl', f'#!{sys.executable}\n' + '''import json, os, pathlib, subprocess, sys, urllib.parse
args = sys.argv[1:]
url = next(arg for arg in args if arg.startswith('https://'))
pathlib.Path(os.environ['API_LOG']).write_text(url)
query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
sha = query['head_sha'][0]
repository = '/'.join(urllib.parse.urlparse(url).path.split('/')[2:4])
if os.environ.get('CI_MUTATE'):
    subprocess.run(['git', '-C', os.environ['DOTFILES_SOURCE'], 'reset', '--hard', os.environ['CI_MUTATE']], check=True, stdout=subprocess.DEVNULL)
run = dict(id=1, run_number=1, run_attempt=1, name='Verify', path='.github/workflows/verify.yml',
           event='push', head_branch=query['branch'][0], head_sha=sha, status='completed', conclusion='success',
           repository={'full_name':repository}, head_repository={'full_name':repository})
case = os.environ.get('CI_CASE', 'success')
if case == 'wrong-sha': run['head_sha'] = 'b' * 40
if case == 'failure': run['conclusion'] = 'failure'
if case == 'queued': run.update(status='queued', conclusion=None)
data = {'total_count': 1, 'workflow_runs': [run]}
if case == 'missing': data = {'total_count': 0, 'workflow_runs': []}
pathlib.Path(args[args.index('-o') + 1]).write_text('not-json' if case == 'malformed' else json.dumps(data))
''')

    def git(self, *args):
        return subprocess.run(['git', *args], env=self.env, text=True, capture_output=True, check=True)

    def script(self, name, body):
        path = self.bin / name
        path.write_text(body)
        path.chmod(0o755)

    def bootstrap(self, *args):
        return subprocess.run(['/bin/sh', str(ROOT / 'bootstrap.sh'), '--non-interactive', *args],
                              env=self.env, text=True, capture_output=True, timeout=20)

    def existing(self):
        self.git('clone', REPOSITORY, str(self.source))

    def test_new_checkout_executes_only_validated_exact_revision(self):
        result = self.bootstrap('--profiles=shell,php')
        self.assertEqual(result.returncode, 0, result.stderr)
        executed = json.loads(self.marker.read_text())
        self.assertEqual(executed['sha'], self.sha)
        self.assertEqual(executed['args'], ['install', '--non-interactive', '--profiles', 'shell,php'])
        self.assertIn('head_sha=' + self.sha, self.api_log.read_text())

    def test_existing_clean_checkout_is_validated(self):
        self.existing()
        result = self.bootstrap('--sync')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(self.marker.read_text())['args'][-1], '--sync')

    def test_invalid_ci_never_executes_checkout_code(self):
        for case in ['failure', 'queued', 'missing', 'malformed', 'wrong-sha']:
            with self.subTest(case=case):
                self.env['CI_CASE'] = case
                result = self.bootstrap()
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(self.marker.exists())
                # Failed validation must not leave an unusable checkout behind.
                self.assertFalse(self.source.exists())

    def test_dirty_existing_checkout_refused_before_ci(self):
        for kind in ['tracked', 'untracked', 'staged']:
            with self.subTest(kind=kind):
                self.existing()
                if kind == 'untracked':
                    (self.source / 'private-file').write_text('fixture private value')
                else:
                    (self.source / 'bin/dotfiles').write_text('malicious fixture')
                    if kind == 'staged':
                        self.git('-C', str(self.source), 'add', 'bin/dotfiles')
                result = self.bootstrap()
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(self.marker.exists())
                self.assertFalse(self.api_log.exists())
                shutil.rmtree(self.source)

    def test_revision_change_during_ci_refused(self):
        self.existing()
        (self.source / 'new-file').write_text('second fixture revision')
        self.git('-C', str(self.source), 'add', '.')
        self.git('-C', str(self.source), '-c', 'user.name=Fixture', '-c', 'user.email=fixture@users.noreply.github.com', 'commit', '-m', 'Second')
        self.env['CI_MUTATE'] = self.sha
        result = self.bootstrap()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('revision changed', result.stderr)
        self.assertFalse(self.marker.exists())

    def test_wrong_origin_refused(self):
        self.existing()
        self.git('-C', str(self.source), 'config', 'remote.origin.url', 'https://github.com/other/repo.git')
        result = self.bootstrap()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.marker.exists())
        self.assertFalse(self.api_log.exists())

    def test_repository_fsmonitor_code_never_runs(self):
        self.existing()
        probe = self.home / 'fsmonitor-executed'
        hook = self.home / 'fsmonitor.sh'
        hook.write_text('#!/bin/sh\ntouch "' + str(probe) + '"\n')
        hook.chmod(0o755)
        self.git('-C', str(self.source), 'config', 'core.fsmonitor', str(hook))
        result = self.bootstrap()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(probe.exists())

    def test_dependencies_only_does_not_clone_or_execute_repository(self):
        result = self.bootstrap('--dependencies-only')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.source.exists())
        self.assertFalse(self.marker.exists())
        self.assertFalse(self.api_log.exists())

    def test_failed_ci_can_be_retried_without_replacing_user_data(self):
        self.env['CI_CASE'] = 'queued'
        self.assertNotEqual(self.bootstrap().returncode, 0)
        self.assertFalse(self.source.exists())
        self.env['CI_CASE'] = 'success'
        result = self.bootstrap()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(self.marker.read_text())['sha'], self.sha)

    def test_configured_repository_and_branch_clone_exact_revision(self):
        repository = 'https://github.com/team/config.git'
        self.git('-C', str(self.remote), 'branch', 'release/review')
        self.git('config', '--file', str(self.config), '--add', f'url.{self.remote}.insteadOf', repository)
        self.env.update(DOTFILES_REPOSITORY=repository, DOTFILES_BRANCH='release/review')
        result = self.bootstrap()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(self.marker.read_text())['sha'], self.sha)
        self.assertEqual(self.git('-C', str(self.source), 'branch', '--show-current').stdout.strip(), 'release/review')
        self.assertIn('/repos/team/config/', self.api_log.read_text())
        self.assertIn('branch=release%2Freview', self.api_log.read_text())
