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
manifest="$repo_root/tooling/tools.json"
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

lock_probe() {
  local lockfile="$1"
  "$venv/bin/python" - "$lockfile" <<'PY'
import importlib.metadata as metadata
import re
import sys

def normalize(name):
    return re.sub(r"[-_.]+", "-", name).lower()

expected = {}
with open(sys.argv[1], encoding="utf-8") as handle:
    for line in handle:
        match = re.match(r"^\s*([A-Za-z0-9][A-Za-z0-9_.-]*)==([^\\\s]+)", line)
        if match:
            expected[normalize(match.group(1))] = match.group(2)

errors = []
for name, wanted in sorted(expected.items()):
    try:
        found = metadata.version(name)
    except metadata.PackageNotFoundError:
        errors.append(f"{name}: missing (expected {wanted})")
        continue
    if found != wanted:
        errors.append(f"{name}: {found} (expected {wanted})")

if errors:
    print("Lockfile mismatch:")
    print("\n".join(errors))
    raise SystemExit(1)
print(f"Lockfile matches installed packages: {len(expected)} pins")
PY
}

if [[ "$profile" == "metal" ]]; then
  python_probe jax jaxlib
  lock_probe "$repo_root/requirements/metal.lock.txt"
  if [[ "${PHENORA_VALIDATE_METAL_DEVICE:-0}" == "1" ]]; then
    ENABLE_PJRT_COMPATIBILITY=1 "$venv/bin/python" - <<'PY'
import jax
print("JAX devices:", jax.devices())
PY
  else
    echo "JAX Metal device probe skipped; set PHENORA_VALIDATE_METAL_DEVICE=1 to require GPU validation."
  fi
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

micro_version="$($venv/bin/python - "$manifest" <<'PY'
import json
import sys
with open(sys.argv[1], encoding="utf-8") as handle:
    print(json.load(handle)["native"]["micromegas"]["version"])
PY
)"
micro_sha256="$($venv/bin/python - "$manifest" <<'PY'
import json
import sys
with open(sys.argv[1], encoding="utf-8") as handle:
    print(json.load(handle)["native"]["micromegas"]["source"]["sha256"])
PY
)"
micro_version_file="$install_dir/micromegas/VERSION"
[[ -f "$micro_version_file" ]] || { echo "Missing micrOMEGAs provenance marker: $micro_version_file" >&2; exit 1; }
grep -Fxq "micrOMEGAs $micro_version" "$micro_version_file" || {
  echo "micrOMEGAs version marker mismatch (expected $micro_version)." >&2
  exit 1
}
grep -Fxq "sha256 $micro_sha256" "$micro_version_file" || {
  echo "micrOMEGAs checksum marker mismatch (expected $micro_sha256)." >&2
  exit 1
}
echo "micrOMEGAs: $micro_version"

if [[ -x "$install_dir/spheno/bin/SPheno" ]]; then
  "$install_dir/spheno/bin/SPheno" --help 2>&1 | head -n 2 || true
fi
ar -t "$install_dir/micromegas/lib/libmicromegas.a" | head -n 2
otool -L "$install_dir/higgstools/lib/libHiggsTools.dylib" | head -n 2
"$install_dir/bsmpt/BSMPT" --help 2>&1 | head -n 2 || true
otool -L "$install_dir/multinest/lib/libmultinest.dylib" | head -n 2
python_probe dynesty getdist jax jaxlib jaxns
lock_probe "$repo_root/requirements/cpu.lock.txt"
"$venv/bin/python" - <<'PY'
import jax
print("JAX devices:", jax.devices())
PY
