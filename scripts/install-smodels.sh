#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 || $1 != --profile || ($2 != cpu && $2 != metal) ]]; then
  echo 'Usage: scripts/install-smodels.sh --profile cpu|metal' >&2
  exit 2
fi
profile="$2"
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
venv="${PHENORA_VENV_ROOT:-$repo_root/.venv}/$profile"
python="$venv/bin/python"
[[ -x "$python" ]] || { echo "Create the $profile environment with bootstrap first." >&2; exit 1; }
[[ "$(uname -s)" == Darwin && "$(uname -m)" == arm64 ]] || {
  echo 'SModelS external-tool installation supports Apple-silicon macOS only.' >&2; exit 1;
}

# Do not recreate environments or rebuild unrelated native tools during an addition.
if [[ "$profile" == cpu ]]; then
  for package in gcc boost cmake gsl; do
    brew list --versions "$package" >/dev/null 2>&1 || \
      HOMEBREW_NO_AUTO_UPDATE=1 HOMEBREW_NO_INSTALL_CLEANUP=1 brew install "$package"
  done
  "$python" "$repo_root/scripts/smodels-toolchain.py" build
else
  "$python" "$repo_root/scripts/smodels-toolchain.py" check_bundle || {
    echo 'Install the CPU SModelS profile first to build the shared external tools.' >&2; exit 1;
  }
fi
"$python" "$repo_root/scripts/smodels-toolchain.py" prepare
"$python" -m pip install --index-url https://pypi.org/simple --require-hashes \
  -r "$repo_root/requirements/$profile.lock.txt"
"$python" -m pip check
"$python" "$repo_root/scripts/smodels-toolchain.py" activate
"$python" "$repo_root/scripts/smodels-toolchain.py" verify
