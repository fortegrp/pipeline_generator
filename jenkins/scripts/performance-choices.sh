#!/usr/bin/env bash
set -euo pipefail

mode="${1:-projects}"
branch="${2:-main}"
project="${3:-}"
tool="${4:-}"

env_file="/var/jenkins_home/performance.env"
cache_root="/var/jenkins_home/script-cache/performance-scripts"

if [ ! -f "${env_file}" ]; then
  exit 0
fi

set -a
. "${env_file}"
set +a

repo_url="${SCRIPT_REPO_URL:-}"
if [ -z "${repo_url}" ] || [ "${repo_url}" = "LOCAL" ]; then
  exit 0
fi

safe_branch="$(printf '%s' "${branch}" | tr -c 'A-Za-z0-9_.-' '_')"
repo_dir="${cache_root}/${safe_branch}"
lock_dir="${cache_root}/${safe_branch}.lock"

mkdir -p "${cache_root}"

with_git_auth() {
  if [ -n "${SCRIPT_REPO_TOKEN:-}" ]; then
    askpass="${cache_root}/git-askpass-${safe_branch}.sh"
    cat > "${askpass}" <<'EOF'
#!/usr/bin/env sh
case "$1" in
  *Username*) printf '%s\n' "${SCRIPT_REPO_USERNAME:-x-access-token}" ;;
  *Password*) printf '%s\n' "${SCRIPT_REPO_TOKEN}" ;;
  *) printf '\n' ;;
esac
EOF
    chmod 700 "${askpass}"
    export GIT_ASKPASS="${askpass}"
    export GIT_TERMINAL_PROMPT=0
  fi
}

refresh_repo() {
  if mkdir "${lock_dir}" 2>/dev/null; then
    trap 'rmdir "${lock_dir}" >/dev/null 2>&1 || true' EXIT
    with_git_auth

    if [ -d "${repo_dir}/.git" ]; then
      git -C "${repo_dir}" fetch --depth 1 origin "${branch}" >/dev/null 2>&1 || true
      git -C "${repo_dir}" checkout -q FETCH_HEAD >/dev/null 2>&1 || true
    else
      rm -rf "${repo_dir}"
      git clone --depth 1 --branch "${branch}" "${repo_url}" "${repo_dir}" >/dev/null 2>&1 || true
    fi
  else
    sleep 1
  fi
}

print_dirs() {
  path="$1"
  if [ -d "${path}" ]; then
    find "${path}" -mindepth 1 -maxdepth 1 -type d -exec basename {} \; | sort
  fi
}

print_dirs_with_files() {
  path="$1"
  if [ -d "${path}" ]; then
    find "${path}" -mindepth 1 -maxdepth 1 -type d | while IFS= read -r child_dir; do
      if find "${child_dir}" -type f | head -1 | grep -q .; then
        basename "${child_dir}"
      fi
    done | sort
  fi
}

print_files() {
  path="$1"
  if [ -d "${path}" ]; then
    find "${path}" -mindepth 1 -maxdepth 1 -type f -exec basename {} \; | sort
  fi
}

tool_for_file() {
  file="$1"
  case "${file}" in
    *.jmx) echo "jmeter" ;;
    *.scala) echo "gatling" ;;
    *.py) echo "locust" ;;
    *.js) echo "k6" ;;
  esac
}

find_project_scripts() {
  project_dir="$1"
  if [ -d "${project_dir}" ]; then
    find "${project_dir}" -type f \( -name '*.js' -o -name '*.jmx' -o -name '*.py' -o -name '*.scala' \) | sort
  fi
}

refresh_repo

case "${mode}" in
  projects)
    base="${repo_dir}/perf_scripts"
    if [ -d "${base}" ]; then
      projects="$(find "${base}" -mindepth 1 -maxdepth 1 -type d | while IFS= read -r project_dir; do
        if find_project_scripts "${project_dir}" | head -1 | grep -q .; then
          basename "${project_dir}"
        fi
      done | sort)"

      default_project="$(printf '%s' "${PROJECT:-}" | tr '[:upper:]' '[:lower:]')"
      if [ -n "${default_project}" ] && printf '%s\n' "${projects}" | grep -qi "^${default_project}$"; then
        printf '%s\n' "${projects}" | awk -v default_project="${default_project}" '
          BEGIN { printed = 0 }
          tolower($0) == default_project && printed == 0 { print; printed = 1; next }
          { rest[++count] = $0 }
          END { for (i = 1; i <= count; i++) print rest[i] }
        '
      else
        printf '%s\n' "${projects}"
      fi
    fi
    ;;
  tools)
    find_project_scripts "${repo_dir}/perf_scripts/${project}" | while IFS= read -r script_file; do
      tool_for_file "${script_file}"
    done | sort -u
    ;;
  scripts)
    find_project_scripts "${repo_dir}/perf_scripts/${project}" | while IFS= read -r script_file; do
      detected_tool="$(tool_for_file "${script_file}")"
      if [ "${detected_tool}" = "${tool}" ]; then
        printf '%s\n' "${script_file#${repo_dir}/}"
      fi
    done | sort
    ;;
esac
