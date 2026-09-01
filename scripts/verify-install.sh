#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/verify-install.sh [--profile cpu|metal]

Checks that each requested tool has been installed. This intentionally performs
installation checks only; it does not run scientific benchmarks or upstream tests.
EOF
}

profile="cpu"
if [[ $# -gt 0 ]]; then
  [[ $# -eq 2 && $1 == "--profile" && ($2 == "cpu" || $2 == "metal") ]] || { usage >&2; exit 2; }
  profile="$2"
fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
install_dir="$repo_root/third_party/install"
venv="$repo_root/.venv/$profile"
[[ -x "$venv/bin/python" ]] || { echo "Missing $profile environment; run bootstrap first." >&2; exit 1; }

python_probe() {
  "$venv/bin/python" - "$@" <<'PY'
import importlib, sys
for name in sys.argv[1:]:
    module = importlib.import_module(name)
    print(f"{name}: {getattr(module, '__version__', 'installed')}")
PY
}

if [[ "$profile" == "metal" ]]; then
  python_probe jax jaxlib
  ENABLE_PJRT_COMPATIBILITY=1 "$venv/bin/python" - <<'PY'
import jax
print("JAX devices:", jax.devices())
PY
  exit 0
fi

for path in \
  "$install_dir/spheno/bin/SPheno" \
  "$install_dir/micromegas/lib/libmicromegas.a" \
  "$install_dir/higgstools/lib/libHiggsTools.dylib" \
  "$install_dir/bsmpt/BSMPT" \
  "$install_dir/multinest/lib/libmultinest.dylib"; do
  [[ -e "$path" ]] || { echo "Missing required artifact: $path" >&2; exit 1; }
  echo "Found: $path"
done

if [[ -x "$install_dir/spheno/bin/SPheno" ]]; then
  "$install_dir/spheno/bin/SPheno" --help 2>&1 | head -n 2 || true
fi
ar -t "$install_dir/micromegas/lib/libmicromegas.a" | head -n 2
otool -L "$install_dir/higgstools/lib/libHiggsTools.dylib" | head -n 2
"$install_dir/bsmpt/BSMPT" --help 2>&1 | head -n 2 || true
otool -L "$install_dir/multinest/lib/libmultinest.dylib" | head -n 2
python_probe dynesty getdist jax jaxlib jaxns
"$venv/bin/python" - <<'PY'
import jax
print("JAX devices:", jax.devices())
PY
