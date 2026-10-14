#!/bin/sh
# Download this file for review, then run it; no remote script is piped into a shell.
set -eu
umask 077
mode=interactive
dependencies_only=0
profiles=shell
sync=0
for arg in "$@"; do
    case $arg in
        --non-interactive) mode=non-interactive ;;
        --dependencies-only) dependencies_only=1 ;;
        --sync) sync=1 ;;
        --profiles=*) profiles=${arg#*=} ;;
        --help) printf '%s\n' 'bootstrap.sh [--non-interactive] [--dependencies-only] [--profiles=shell,php,...] [--sync]'; exit 0 ;;
        *) printf 'Unknown bootstrap option: %s\n' "$arg" >&2; exit 2 ;;
    esac
done
# BEGIN EMBEDDED CI VALIDATOR
# Standalone CI gate; keep the embedded bootstrap copy identical.
# ci_verify_commit SHA [REPOSITORY] [BRANCH]: silent success, failure returns nonzero.
# REPOSITORY/BRANCH default to DOTFILES_REPOSITORY/DOTFILES_BRANCH, then public master.
ci_repository_slug() {
    case $1 in
        https://github.com/*) _ci_slug=${1#https://github.com/} ;;
        git@github.com:*) _ci_slug=${1#git@github.com:} ;;
        *) printf '%s\n' 'CI validation requires a GitHub repository URL without credentials.' >&2; return 1 ;;
    esac
    _ci_slug=${_ci_slug%.git}
    printf '%s\n' "$_ci_slug" | LC_ALL=C grep -Eq '^[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_.-]+$' || {
        printf '%s\n' 'Invalid GitHub repository URL.' >&2; return 1;
    }
    printf '%s\n' "$_ci_slug"
}
ci_verify_commit() (
    umask 077
    _ci_sha=$1
    _ci_repository=${2:-${DOTFILES_REPOSITORY:-https://github.com/phcorp/dotfiles.git}}
    _ci_branch=${3:-${DOTFILES_BRANCH:-master}}
    case $_ci_sha in *[!a-f0-9]*|'') printf '%s\n' 'Invalid CI commit identifier.' >&2; return 1 ;; esac
    [ "${#_ci_sha}" -eq 40 ] || { printf '%s\n' 'Invalid CI commit identifier.' >&2; return 1; }
    _ci_slug=$(ci_repository_slug "$_ci_repository") || return
    git check-ref-format --branch "$_ci_branch" >/dev/null 2>&1 || { printf '%s\n' 'Invalid CI branch.' >&2; return 1; }
    if ! command -v jq >/dev/null 2>&1 || ! command -v curl >/dev/null 2>&1; then
        printf '%s\n' 'curl and jq are required for CI validation.' >&2; return 1
    fi
    _ci_branch_query=$(jq -nr --arg branch "$_ci_branch" '$branch | @uri') || return
    _ci_work=$(mktemp -d) || return
    trap 'rm -rf "$_ci_work"' EXIT
    trap 'exit 129' HUP
    trap 'exit 130' INT
    trap 'exit 143' TERM
    _ci_url="https://api.github.com/repos/$_ci_slug/actions/runs?head_sha=$_ci_sha&branch=$_ci_branch_query&event=push&per_page=100"
    if [ -n "${GITHUB_TOKEN:-}" ]; then
        case $GITHUB_TOKEN in *'
'*|*"$(printf '\r')"*) printf '%s\n' 'Invalid GitHub authentication token.' >&2; return 1 ;; esac
        printf 'Authorization: Bearer %s\n' "$GITHUB_TOKEN" > "$_ci_work/header"
        chmod 600 "$_ci_work/header"
        curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 \
            --connect-timeout 15 --max-time 30 --header 'Accept: application/vnd.github+json' \
            --header 'X-GitHub-Api-Version: 2022-11-28' --header "@$_ci_work/header" \
            "$_ci_url" -o "$_ci_work/runs.json" 2>/dev/null
    else
        curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 \
            --connect-timeout 15 --max-time 30 --header 'Accept: application/vnd.github+json' \
            --header 'X-GitHub-Api-Version: 2022-11-28' "$_ci_url" -o "$_ci_work/runs.json" 2>/dev/null
    fi || { printf '%s\n' 'GitHub CI response unavailable; refusing unverified repository code.' >&2; return 1; }
    jq -e --slurp --arg sha "$_ci_sha" --arg branch "$_ci_branch" --arg repository "$_ci_slug" '
        def positive_integer: type == "number" and . > 0 and floor == .;
        def valid_run:
            type == "object" and
            (.id | positive_integer) and (.run_number | positive_integer) and
            (.run_attempt | positive_integer) and
            ([.name, .path, .event, .head_branch, .head_sha, .status] | all(type == "string")) and
            has("conclusion") and (.head_sha | test("^[a-f0-9]{40}$")) and
            (.repository.full_name | type == "string") and
            (.head_repository.full_name | type == "string") and
            ((.repository.full_name | ascii_downcase) == ($repository | ascii_downcase)) and
            ((.head_repository.full_name | ascii_downcase) == ($repository | ascii_downcase)) and
            (.status | IN("completed", "queued", "in_progress", "requested", "waiting", "pending")) and
            (.conclusion == null or (.conclusion | IN("success", "failure", "cancelled", "timed_out", "action_required", "neutral", "skipped", "stale", "startup_failure"))) and
            ((.status == "completed") == (.conclusion != null)) and
            (.head_sha == $sha);
        length == 1 and (.[0] |
        type == "object" and
        (.total_count | type == "number" and . >= 0 and floor == .) and
        (.workflow_runs | type == "array") and
        (.total_count == (.workflow_runs | length)) and
        (.workflow_runs | all(valid_run)) and
        ((.workflow_runs | map(.id) | unique | length) == (.workflow_runs | length)) and
        ([.workflow_runs[] | select(.name == "Verify" and
            (.path == ".github/workflows/verify.yml" or .path == (".github/workflows/verify.yml@" + $branch) or .path == (".github/workflows/verify.yml@refs/heads/" + $branch)) and
            .event == "push" and .head_branch == $branch)] |
            sort_by([.run_number, .run_attempt, .id]) | last |
            .status == "completed" and .conclusion == "success"))
    ' "$_ci_work/runs.json" >/dev/null 2>&1 || {
        printf '%s\n' 'Latest exact-commit Verify push run is missing, invalid, incomplete, or unsuccessful.' >&2; return 1;
    }
)
# END EMBEDDED CI VALIDATOR

privileged() {
    if [ "$(id -u)" = 0 ]; then "$@"
    elif [ "$mode" = non-interactive ]; then sudo -n "$@"
    else sudo "$@"; fi
}
sha256() {
    if command -v sha256sum >/dev/null 2>&1; then sha256sum < "$1" | cut -d ' ' -f 1
    else shasum -a 256 < "$1" | cut -d ' ' -f 1; fi
}
download() {
    curl -fsSL --proto '=https' --tlsv1.2 --connect-timeout 15 --max-time 300 "$1" -o "$2"
    [ "$(sha256 "$2")" = "$3" ] || { printf '%s\n' 'Bootstrap checksum mismatch.' >&2; exit 1; }
}
task_tmp=$(mktemp -d)
trap 'rm -rf "$task_tmp"' EXIT HUP INT TERM
case $(uname -s) in
    Darwin)
        platform=darwin
        for prefix in /opt/homebrew /usr/local; do
            [ ! -x "$prefix/bin/brew" ] || PATH=$prefix/bin:$PATH
        done
        export PATH
        if ! command -v brew >/dev/null 2>&1; then
            xcode-select -p >/dev/null 2>&1 || { printf '%s\n' 'Install Apple Command Line Tools with xcode-select --install, then rerun bootstrap.' >&2; exit 1; }
            download https://raw.githubusercontent.com/Homebrew/install/7a3f48c7e498d7df3237fd41c30f4d492857edf4/install.sh "$task_tmp/homebrew.sh" 5f333bbe53bc490e51e7ccb1df8779b3dd6ee73a1a7379efda216edb08ccb148
            if [ "$mode" = non-interactive ]; then NONINTERACTIVE=1 /bin/bash "$task_tmp/homebrew.sh"
            else /bin/bash "$task_tmp/homebrew.sh"; fi
            for prefix in /opt/homebrew /usr/local; do [ ! -x "$prefix/bin/brew" ] || PATH=$prefix/bin:$PATH; done
            export PATH
        fi
        for prerequisite in git curl jq python3; do
            if ! command -v "$prerequisite" >/dev/null 2>&1; then
                case $prerequisite in python3) brew install python ;; *) brew install "$prerequisite" ;; esac
            fi
        done ;;
    Linux)
        platform=linux
        if ! command -v git >/dev/null 2>&1 || ! command -v curl >/dev/null 2>&1 || ! command -v jq >/dev/null 2>&1 || ! command -v unzip >/dev/null 2>&1 || ! command -v python3 >/dev/null 2>&1; then
            if command -v apt-get >/dev/null 2>&1; then
                privileged env DEBIAN_FRONTEND=noninteractive apt-get update
                privileged env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends git curl jq ca-certificates unzip python3
            elif command -v dnf >/dev/null 2>&1; then privileged dnf install -y git curl jq ca-certificates unzip python3
            else printf '%s\n' 'Supported Linux managers: apt and dnf.' >&2; exit 1; fi
        fi ;;
    *) printf '%s\n' 'Supported systems: macOS and Linux.' >&2; exit 1 ;;
esac
case $(uname -m) in arm64|aarch64) arch=arm64 ;; x86_64|amd64) arch=amd64 ;; *) printf '%s\n' 'Supported architectures: arm64 and x86_64.' >&2; exit 1 ;; esac
: "${XDG_DATA_HOME:=$HOME/.local/share}"
safe_directory() {
    [ ! -L "$1" ] || { printf '%s\n' 'Bootstrap refuses symlinked installation directories.' >&2; exit 1; }
    ancestor=$1
    while [ ! -d "$ancestor" ]; do
        [ ! -L "$ancestor" ] || { printf '%s\n' 'Bootstrap refuses broken directory symlinks.' >&2; exit 1; }
        ancestor=$(dirname "$ancestor")
    done
    physical=$(CDPATH='' cd "$ancestor" && pwd -P)
    physical_home=$(CDPATH='' cd "$HOME" && pwd -P)
    case "$physical/" in "$physical_home/"*) ;; *) printf '%s\n' 'Bootstrap directory escapes HOME.' >&2; exit 1 ;; esac
}
safe_directory "$HOME/.local/bin"
mkdir -p "$HOME/.local/bin"
PATH=$HOME/.local/bin:$PATH
export PATH
if ! command -v chezmoi >/dev/null 2>&1; then
    case $platform-$arch in
        darwin-amd64) checksum=0ec1869c60752644863bc4690878a290455f0d35c6e9b200ca4a822b35d2be54 ;;
        darwin-arm64) checksum=19a8d9778d90476cc2f0463be69e9d82e2b91ba7b2361dbfc5348f243b1ba731 ;;
        linux-amd64) checksum=a3f958acb7d0e5d53fa43c2eec9bc8ae3b4fba8bcbfdce29a8881ca3ffc20a53 ;;
        linux-arm64) checksum=e60275b27f505ae2086bfb87b144eacf7377a89803120f6bd933d1852a93b0c6 ;;
    esac
    download "https://github.com/twpayne/chezmoi/releases/download/v2.73.1/chezmoi_2.73.1_${platform}_${arch}.tar.gz" "$task_tmp/chezmoi.tgz" "$checksum"
    tar -xzf "$task_tmp/chezmoi.tgz" -C "$task_tmp" chezmoi
    [ ! -L "$HOME/.local/bin/chezmoi" ] || { printf '%s\n' 'Refusing to overwrite chezmoi symlink.' >&2; exit 1; }
    cp "$task_tmp/chezmoi" "$HOME/.local/bin/chezmoi"
    chmod 755 "$HOME/.local/bin/chezmoi"
fi
[ "$dependencies_only" = 0 ] || exit 0
source_dir=${DOTFILES_SOURCE:-$XDG_DATA_HOME/chezmoi}
repository=${DOTFILES_REPOSITORY:-https://github.com/phcorp/dotfiles.git}
branch=${DOTFILES_BRANCH:-master}
expected_repository=$(ci_repository_slug "$repository")
git check-ref-format --branch "$branch" >/dev/null 2>&1 || { printf '%s\n' 'Invalid bootstrap branch.' >&2; exit 1; }
safe_directory "$source_dir"
# Clone without checking out: no repository code, checkout filter or hook runs before CI.
new_checkout=0
checkout_dir=$source_dir
if [ ! -e "$source_dir" ]; then
    checkout_dir=$task_tmp/checkout
    git -c core.hooksPath=/dev/null clone --no-checkout --branch "$branch" "$repository" "$checkout_dir"
    new_checkout=1
elif ! git -C "$source_dir" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    printf '%s\n' 'Source path already exists and is not a checkout.' >&2; exit 1
fi
export GIT_NO_REPLACE_OBJECTS=1
checkout_root=$(git -C "$checkout_dir" rev-parse --show-toplevel)
source_physical=$(CDPATH='' cd "$checkout_dir" && pwd -P)
root_physical=$(CDPATH='' cd "$checkout_root" && pwd -P)
[ "$source_physical" = "$root_physical" ] || { printf '%s\n' 'Bootstrap source must be the checkout root.' >&2; exit 1; }
origin=$(git -C "$checkout_dir" config --get remote.origin.url) || { printf '%s\n' 'Bootstrap checkout has no origin.' >&2; exit 1; }
actual_repository=$(ci_repository_slug "$origin")
[ "$(printf '%s' "$actual_repository" | tr '[:upper:]' '[:lower:]')" = "$(printf '%s' "$expected_repository" | tr '[:upper:]' '[:lower:]')" ] || {
    printf '%s\n' 'Bootstrap checkout origin differs from the configured repository.' >&2; exit 1;
}
validated_sha=$(git -C "$checkout_dir" rev-parse --verify 'HEAD^{commit}')
checkout_clean() {
    # status must not invoke repository-configured fsmonitor commands or submodule code.
    [ -z "$(git -c core.fsmonitor=false -c core.untrackedCache=false -C "$checkout_dir" ls-files --stage | awk '$1 == "160000" {print}')" ] || { printf '%s\n' 'Bootstrap does not execute checkouts containing submodules.' >&2; return 1; }
    _bootstrap_status=$(git -c core.fsmonitor=false -c core.untrackedCache=false -C "$checkout_dir" status --porcelain=v1 --untracked-files=all --ignore-submodules=all) || return
    [ -z "$_bootstrap_status" ] || { printf '%s\n' 'Bootstrap refuses a dirty checkout; preserve or resolve its local changes first.' >&2; return 1; }
}
if [ "$new_checkout" = 0 ]; then checkout_clean; fi
if ! ci_verify_commit "$validated_sha" "$repository" "$branch"; then
    printf '%s\n' 'Bootstrap stopped before applying dotfiles. Ensure Verify succeeds for this exact revision on the configured repository and branch; check GitHub API access or rate limits, then rerun bootstrap.' >&2
    exit 1
fi
if [ "$new_checkout" = 1 ]; then
    git -c core.hooksPath=/dev/null -C "$checkout_dir" checkout --force "$branch"
fi
# The revision and cleanliness checked by CI must still hold at the execution boundary.
[ "$(git -C "$checkout_dir" rev-parse --verify 'HEAD^{commit}')" = "$validated_sha" ] || { printf '%s\n' 'Checkout revision changed during CI validation.' >&2; exit 1; }
checkout_clean
if [ "$new_checkout" = 1 ]; then
    if [ -e "$source_dir" ] || [ -L "$source_dir" ]; then printf '%s\n' 'Bootstrap source appeared during validation; refusing replacement.' >&2; exit 1; fi
    safe_directory "$source_dir"
    mkdir -p "$(dirname "$source_dir")"
    mv "$checkout_dir" "$source_dir"
    checkout_dir=$source_dir
    [ "$(git -C "$checkout_dir" rev-parse --verify 'HEAD^{commit}')" = "$validated_sha" ] || { printf '%s\n' 'Checkout revision changed before execution.' >&2; exit 1; }
    checkout_clean
fi
if [ "$mode" = interactive ]; then
    DOTFILES_SOURCE=$source_dir "$source_dir/bin/dotfiles" wizard
elif [ "$sync" = 1 ]; then
    DOTFILES_SOURCE=$source_dir "$source_dir/bin/dotfiles" install --non-interactive --profiles "$profiles" --sync
else
    DOTFILES_SOURCE=$source_dir "$source_dir/bin/dotfiles" install --non-interactive --profiles "$profiles"
fi
