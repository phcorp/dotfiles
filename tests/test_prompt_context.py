import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'home/dot_config/dotfiles/executable_prompt-context.py'


class PromptContext(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='dotfiles-prompt-')
        self.addCleanup(self.temp.cleanup)
        self.home = pathlib.Path(self.temp.name) / 'home'
        self.home.mkdir()
        self.project = self.home / 'project with spaces'
        self.project.mkdir()
        self.child = self.project / 'src/deep'
        self.child.mkdir(parents=True)
        self.env = dict(os.environ, HOME=str(self.home), AWS_REGION='eu-west-1', TERM='xterm-256color')

    def detected(self, module, directory=None):
        result = subprocess.run(['python3', str(SCRIPT), module, '--detect'],
                                cwd=directory or self.project, env=self.env,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.stdout, '')
        self.assertEqual(result.stderr, '')
        self.assertIn(result.returncode, (0, 1))
        return result.returncode == 0

    def test_home_global_settings_never_count_as_projects(self):
        (self.home / '.nvmrc').write_text('24\n')
        (self.home / 'lua').mkdir()
        (self.home / '.aws').mkdir()
        (self.home / '.aws-project').touch()
        for module in ('nodejs', 'lua', 'aws'):
            self.assertFalse(self.detected(module, self.home))
            self.assertFalse(self.detected(module, self.child))

    def test_plain_folder_and_browser_script_do_not_show_node(self):
        (self.project / 'browser.js').write_text('// browser script\n')
        self.assertFalse(self.detected('nodejs'))
        self.assertFalse(self.detected('aws'))

    def test_node_manifest_applies_in_nested_directories(self):
        (self.project / 'package.json').write_text('{}')
        self.assertTrue(self.detected('nodejs'))
        self.assertTrue(self.detected('nodejs', self.child))
        self.assertFalse(self.detected('aws', self.child))

    def test_git_boundary_prevents_unrelated_parent_context(self):
        (self.project / 'package.json').write_text('{}')
        (self.child / '.git').write_text('gitdir: fixture\n')
        self.assertFalse(self.detected('nodejs', self.child))

    def test_lua_source_applies_in_nested_directories(self):
        (self.project / 'main.lua').write_text('-- source\n')
        self.assertTrue(self.detected('lua', self.child))

    def test_aws_sdk_dependencies_and_explicit_marker(self):
        manifest = self.project / 'package.json'
        manifest.write_text(json.dumps({'dependencies': {'@aws-sdk/client-s3': '*'}}))
        self.assertTrue(self.detected('aws', self.child))
        manifest.write_text('not valid json')
        self.assertFalse(self.detected('aws', self.child))
        (self.project / '.aws-project').touch()
        self.assertTrue(self.detected('aws', self.child))

    def test_terraform_aws_provider_is_specific(self):
        terraform = self.project / 'main.tf'
        terraform.write_text('provider "google" {}\n')
        self.assertFalse(self.detected('aws'))
        terraform.write_text('provider "aws" {}\n')
        self.assertTrue(self.detected('aws', self.child))

    def test_serverless_provider_is_specific(self):
        serverless = self.project / 'serverless.yml'
        serverless.write_text('provider:\n  name: azure\n')
        self.assertFalse(self.detected('aws'))
        serverless.write_text('provider:\n  name: aws\n')
        self.assertTrue(self.detected('aws'))

    @unittest.skipUnless(shutil.which('starship'), 'Starship is optional in logic-test environments')
    def test_actual_prompt_hidden_at_home_and_visible_in_node_aws_project(self):
        config = self.home / '.config'
        helper = config / 'dotfiles/prompt-context.py'
        helper.parent.mkdir(parents=True)
        shutil.copy2(SCRIPT, helper)
        helper.chmod(0o755)
        prompt_config = config / 'starship.toml'
        source = (ROOT / 'home/dot_config/starship.toml').read_text()
        source = source.replace('[aws]\n', '[aws]\nforce_display = true\n')
        prompt_config.write_text(source)
        self.env.update(XDG_CONFIG_HOME=str(config), STARSHIP_CONFIG=str(prompt_config))
        (self.home / '.nvmrc').write_text('24\n')
        (self.home / 'lua').mkdir()
        def render(directory):
            environment = dict(self.env, PWD=str(directory))
            result = subprocess.run(['starship', 'prompt'], cwd=directory, env=environment,
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            return result.stdout
        home_prompt = render(self.home)
        self.assertNotIn('via ', home_prompt)
        self.assertNotIn('eu-west-1', home_prompt)
        (self.project / 'package.json').write_text(json.dumps({'dependencies': {'@aws-sdk/client-s3': '*'}}))
        project_prompt = render(self.child)
        self.assertIn('eu-west-1', project_prompt)
        if shutil.which('node'):
            self.assertIn('via ', project_prompt)
