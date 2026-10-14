# Recovery, backups, and uninstall

## Before changing an existing machine

```sh
dotfiles repair --dry-run
dotfiles doctor
```

Preview identifies planned changes and blockers without modifying configuration,
selections, ownership, software, or schedulers. Review private overrides locally.
For a first migration, review and run `scripts/migrate-local.py` from the source
checkout before installation. It copies selected literal settings and app hooks
into private overrides; it does not execute or publicly copy old startup files.

Original managed files are saved under `$DOTFILES_STATE/originals` (normally
`~/.local/state/dotfiles/originals`). Private backups, Git credential settings,
and overrides remain outside the public checkout. Keep them until recovery and
fresh Bash/Zsh sessions have been verified.

## Interrupted or failed application

Start with a read-only diagnosis:

```sh
dotfiles doctor
```

Locks record their owner PID, host, and process start time. `doctor` distinguishes
an active owner, a verified stale owner, and an unknown owner. Age alone does not
prove that a lock is stale.

- **Active:** the recorded process still matches. Wait for it to finish; never
  remove its lock or recover concurrently.
- **Stale:** the owner exited or its PID was reused, verified on the recorded
  host. Reclaim the lifecycle lock explicitly with `recover --unlock-stale`.
- **Unknown:** legacy/malformed ownership, a different host, or inaccessible
  process information prevents verification. Review the private owner metadata
  and original host; the CLI never automatically removes this lock.

For a verified stale lifecycle lock:

```sh
dotfiles recover --unlock-stale
```

With no blocking lock, use `dotfiles recover`. The unlock option applies only to
recovery and refuses active or unknown locks. Reclaiming a stale lock without a
transaction releases the lock; there is no configuration to roll back. These
owner diagnostics apply to the lifecycle lock. Tool/application locks are
separate; verify that their operation has stopped before any manual recovery.

Recovery treats the journal's atomic commit marker as the boundary:

- A **committed journal** means the new configuration and recorded revision are
  already accepted. Recovery only cleans up the journal and preserves that state.
- An **incomplete transaction** restores its saved source revision, managed files,
  ownership/selection metadata, and original-backup bookkeeping. Source recovery
  accepts only the recorded old or candidate revision; dirty source, new manual
  commits, unknown revisions, or unsafe paths stop recovery before restoration.

Preserve the transaction and original backups if recovery cannot safely finish.
Resolve the stated blocker, preserving manual changes separately, then retry.
After recovery, use `doctor` and validate fresh Bash/Zsh sessions. Scheduler state
is separate from shell startup; disable synchronization when appropriate after
any active operation has completed.

## Locally modified files or blocked synchronization

Automatic synchronization stops for dirty source, changed managed targets,
divergence, mismatched remotes, or unavailable/unsuccessful exact-commit CI.
These conditions retain the current configuration. Move machine-specific changes
to private overrides, review public changes separately, and retry after the
blocker has been resolved.

`--force` authorizes replacement of modified managed files. Use it only after
preserving edits and reviewing a preview:

```sh
dotfiles repair --force --dry-run
dotfiles repair --force
```

Unavailable CI is not a reason to disable validation. Wait for the configured
branch's Verify push run or restore network/API access. A failed initial
bootstrap leaves no unverified checkout installed and can be retried.

## Uninstall configuration or remove apps

```sh
dotfiles uninstall --dry-run
dotfiles uninstall
```

Uninstallation disables owned synchronization and restores original files.
Changed managed files are preserved and reported with a nonzero status. Private
overrides, backups, application data, source checkout, and installed software
remain. Reinstalling a clean configuration is idempotent.

Application removal is a separate explicit operation:

```sh
dotfiles apps remove hoppscotch --dry-run
dotfiles apps remove hoppscotch
```

Only dotfiles-owned installations can be removed. Installed dependents, changed
owned files, or unverifiable ownership block removal. Shared prerequisites and
runtime managers remain. See [application behavior](applications.md) for native,
Flatpak, App Store, and pinned-bundle limitations.
