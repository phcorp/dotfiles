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
        curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 \
            --connect-timeout 15 --max-time 30 --header 'Accept: application/vnd.github+json' \
            --header 'X-GitHub-Api-Version: 2022-11-28' --header "Authorization: Bearer $GITHUB_TOKEN" \
            "$_ci_url" -o "$_ci_work/runs.json" 2>/dev/null
    else
        curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 \
            --connect-timeout 15 --max-time 30 --header 'Accept: application/vnd.github+json' \
            --header 'X-GitHub-Api-Version: 2022-11-28' "$_ci_url" -o "$_ci_work/runs.json" 2>/dev/null
    fi || { printf '%s\n' 'GitHub CI response unavailable; refusing unverified repository code.' >&2; return 1; }
    jq -e --arg sha "$_ci_sha" --arg branch "$_ci_branch" --arg repository "$_ci_slug" '
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
            .status == "completed" and .conclusion == "success")
    ' "$_ci_work/runs.json" >/dev/null 2>&1 || {
        printf '%s\n' 'Latest exact-commit Verify push run is missing, invalid, incomplete, or unsuccessful.' >&2; return 1;
    }
)
