# Changelog

## Private Git setup

- Add optional wizard and unattended Git setup with redacted status/previews,
  owner-only native Git input, conditional private profiles, and recoverable
  configuration changes.
- Supply shared defaults for new `main` branches, fast-forward-only pulls,
  pruning, simple pushes, and explicitly configured identity.
- Preserve existing SSH/keychain/credential integrations; support explicit local
  SSH/OpenPGP signing choices without generating keys, contacting remotes, or
  silently falling back on signing errors.
- Retain the private Git overlay and its active include after uninstallation.

## Reliability and reuse

- Validate the exact bootstrap revision against successful Verify CI before
  executing cloned code; reject unavailable, incomplete, and invalid responses.
  Require exactly one JSON document, including with older jq versions.
- Preview file differences, conflicts, selections, and package plans without
  modifying private configuration, ownership records, or scheduler state.
- Recover interrupted apply/update transactions with prior files, backups,
  selection, ownership, and source revision preserved; explicitly diagnose and
  reclaim stale locks without removing active or unverifiable owners. Minimal
  Linux systems use boot identity and process start ticks without optional
  process-listing or hostname packages.
- Audit the exact reviewed head in PR validation rather than GitHub-generated
  merge metadata; retain public commit identities when merging.
- Make repository, synchronization branch, and public publication identity
  configurable without rewriting existing private Git identity settings.
- Add deterministic CI and actual interruption tests, reproducible startup and
  prompt measurements, focused guides, and the maintainer-selected MIT license.
- Retain eager runtime initialization and current prompt behavior: measurements
  did not justify the proposed prompt consolidation.

## cmux

- Add cmux installation, updates, and owned-only removal on macOS, preserving
  existing apps and exposing the bundled CLI. Use WezTerm as the Linux equivalent.

## Desktop application lifecycle

- Add requested desktop apps and documented Linux equivalents to the catalog.
- Add wizard and unattended app installation, update, and owned-only removal.
- Preserve existing applications and app data; keep authentication private.
- Add signed user-scoped Flatpak support and official native GUI installers.

## Project-aware prompt

- Show Node, Lua, and AWS context only in relevant projects and subdirectories.
- Ignore global HOME settings and unrelated parent repositories; keep AWS
  account/profile identities hidden.

## Portable overhaul

- Replace the legacy shell files with chezmoi-managed Bash/Zsh configuration.
- Add portable lifecycle wizard, first-use dependencies, backups, recovery,
  private overrides, and hourly CI-gated pull synchronization.
- Add selectable developer profiles, native Linux installation, verified
  upstream releases, and ownership-aware update/removal.
- Retire unsafe eval-based helpers, destructive Git synchronization, and
  working-directory-dependent PATH entries.
- Add macOS/Linux behavioral tests, package validation, and publication privacy
  checks. Public history starts fresh with a GitHub noreply identity.
