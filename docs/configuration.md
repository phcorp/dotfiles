# Configuration and reuse

## Locations and privacy

| Purpose | Default location |
| --- | --- |
| Public source checkout | `~/.local/share/chezmoi` |
| Private CLI configuration | `~/.config/dotfiles` |
| Private backups, ownership, transactions | `~/.local/state/dotfiles` |
| User commands | `~/.local/bin` |

XDG configuration/state/data directories can be relocated inside HOME. Paths with
spaces are supported; tabs/newlines and directory symlinks escaping HOME are
rejected. Source files are public configuration only. Private overrides, settings,
credentials, histories, backups, and application sessions remain outside Git.

Private overrides under `$XDG_CONFIG_HOME/dotfiles/local/`:

- `env.sh`: portable environment and machine paths.
- `bash.sh`, `zsh.sh`: final interactive shell overrides.
- `pre-bash.sh`, `pre-zsh.sh`: early interactive integration.
- `login-bash.sh`, `login-zsh.sh` and their `pre-login-*` equivalents: login hooks.
- `gitconfig`: preserved legacy Git identity, credential helpers, conditional includes.
- `git/config`: Git setup output, included after the legacy private file.
- `git/setup-input.gitconfig`: owner-only native Git input for unattended setup.

Overrides are deliberate user shell code. The lifecycle CLI never imports them
into public source or publishes them. Put credentials in the system credential
store or an independently configured secret manager. Set `DOTFILES_INIT_RVM=0`
in private environment overrides to avoid initializing an installed RVM.

Use [private Git setup](git.md) for identity, optional signing, secure credential
helpers, and repository-directory profiles. Existing SSH configuration and keys
remain in place. Git setup is separate from the dotfiles publication identity.

## Repository and publication settings

Defaults are the public `phcorp/dotfiles` repository, branch `master`, and the
maintainer's matching GitHub noreply alias. Override them with environment
variables or an owner-only private file at `$DOTFILES_CONFIG/settings`:

```text
DOTFILES_REPOSITORY=https://github.com/example-org/dotfiles.git
DOTFILES_BRANCH=master
DOTFILES_PUBLISH_NAME=maintainer-alias
DOTFILES_PUBLISH_EMAIL=12345+maintainer-alias@users.noreply.github.com
```

Replace the examples with your repository and public GitHub alias. Create the
file with `umask 077`; an existing file needs `chmod 600`. It must belong to the
current user, be a regular file, and remain inside HOME. `0400` is also accepted.

The format is literal `KEY=value`, one known key per line. Blank lines and lines
beginning with `#` are accepted. No `export`, shell quoting, interpolation,
command substitution, duplicate keys, or arbitrary keys are evaluated. Environment
values take precedence; an explicitly empty environment value fails validation.

Repository URLs must be credential-free GitHub HTTPS or `git@github.com:` URLs.
The branch must be a literal valid Git branch. The publication name must match
the alias in its `@users.noreply.github.com` email. Diagnostics reject invalid
values without printing private identity or credential values.

Effective fetch and push URLs for `origin`, including Git URL rewrites and extra
URLs, must identify the configured repository. A mismatch stops synchronization
or publishing. The CLI does not rewrite private Git identity settings; publishing
sets public author/committer metadata only for the publishing process.

## Use a fork

1. Fork the repository and keep its MIT license and attribution.
2. Enable GitHub Actions and ensure **Verify** completes on a push to your chosen
   branch. A pull-request or manual workflow run is not the required push run.
3. Review your fork's bootstrap script and supply its repository/branch:

   ```sh
   DOTFILES_REPOSITORY=https://github.com/example-org/dotfiles.git \
   DOTFILES_BRANCH=master sh bootstrap.sh
   ```

4. Save matching private settings and use an `origin` that points to your fork.
5. Set your public noreply alias before `dotfiles publish`; existing reachable Git
   history is also checked for public author/committer metadata.

Bootstrap accepts repository/branch environment settings before any checkout
exists. The installed CLI additionally reads the private settings file. Reuse
requires a reviewed repository workflow with the same Verify name/path; changing
that convention requires an intentional validator change.

## Prompt and helpers

Node, Lua, and AWS prompt indicators appear only in matching projects and their
subdirectories. Detection stops at HOME or a Git boundary and never executes
project scripts or calls cloud APIs. HOME-wide settings do not count as project
markers. AWS detection recognizes standard SAM/CDK/Amplify, SDK, Terraform,
Serverless, and CloudFormation markers; add an empty `.aws-project` file for
other AWS projects. Only the region is displayed, not account identities.

`ls`, `ll`, and `la` use eza with a system `ls` fallback. `sc` invokes a project's
Symfony console with quoted arguments. `tsplit` passes arguments to
`tmux split-window`; `ssh-use-key` adds a key to an existing agent. Installed
runtime managers and project runtime-version files retain their own behavior.
