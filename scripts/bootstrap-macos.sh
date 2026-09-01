#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/bootstrap-macos.sh [--profile cpu|metal]

Builds the reproducible local phenora toolchain. The CPU profile installs all
native and Python tools. The Metal profile creates only the experimental,
isolated JAX Metal Python environment.
EOF
}

profile="cpu"
if [[ $# -gt 0 ]]; then
  [[ $# -eq 2 && $1 == "--profile" && ($2 == "cpu" || $2 == "metal") ]] || { usage >&2; exit 2; }
  profile="$2"
fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
manifest="$repo_root/tooling/tools.json"
third_party="$repo_root/third_party"
source_dir="$third_party/src"
build_dir="$third_party/build"
install_dir="$third_party/install"
requirements_dir="$repo_root/requirements"

require() { command -v "$1" >/dev/null 2>&1 || { echo "Missing required command: $1" >&2; exit 1; }; }
require git
require curl
require shasum
require sw_vers

[[ "$(uname -s)" == "Darwin" ]] || { echo "This installer supports macOS only." >&2; exit 1; }
[[ "$(uname -m)" == "arm64" ]] || { echo "This installer supports Apple-silicon (arm64) Macs only." >&2; exit 1; }
xcode-select -p >/dev/null 2>&1 || { echo "Install Xcode Command Line Tools first: xcode-select --install" >&2; exit 1; }
require brew
brew_prefix="$(brew --prefix)"

# No upgrade is requested: only missing prerequisites are installed.
brew_packages=(gcc open-mpi openblas make pkgconf python@3.11 gsl nlopt eigen nlohmann-json)
for package in "${brew_packages[@]}"; do
  brew list --versions "$package" >/dev/null 2>&1 || brew install "$package"
done

python_bin="$(brew --prefix python@3.11)/bin/python3.11"
[[ -x "$python_bin" ]] || { echo "Homebrew Python 3.11 was not installed correctly." >&2; exit 1; }
mkdir -p "$source_dir" "$build_dir" "$install_dir"

source_value() {
  local tool="$1" key="$2"
  "$python_bin" - "$manifest" "$tool" "$key" <<'PY'
import json, sys
path, tool, key = sys.argv[1:]
with open(path) as handle:
    item = json.load(handle)["native"][tool]["source"]
print(item[key])
PY
}

record_archive_hash() {
  local tool="$1" archive="$2" digest
  digest="$(shasum -a 256 "$archive" | awk '{print $1}')"
  "$python_bin" - "$manifest" "$tool" "$digest" <<'PY'
import json, sys
path, tool, digest = sys.argv[1:]
with open(path) as handle:
    document = json.load(handle)
document["native"][tool]["source"]["sha256"] = digest
with open(path, "w") as handle:
    json.dump(document, handle, indent=2)
    handle.write("\n")
PY
}

clone_at_revision() {
  local tool="$1" destination="$2" url revision
  url="$(source_value "$tool" url)"
  revision="$(source_value "$tool" revision)"
  if [[ ! -d "$destination/.git" ]]; then
    git clone "$url" "$destination"
  fi
  git -C "$destination" fetch --tags origin
  git -C "$destination" checkout --detach "$revision"
}

create_python_environment() {
  local environment="$1" requirements="$2" lockfile="$3"
  local venv="$repo_root/.venv/$environment"
  "$python_bin" -m venv "$venv"
  "$venv/bin/python" -m pip install --index-url https://pypi.org/simple --upgrade pip
  "$venv/bin/python" -m pip install --index-url https://pypi.org/simple -r "$requirements"
  "$venv/bin/python" -m pip freeze --all | LC_ALL=C sort > "$lockfile"
}

if [[ "$profile" == "metal" ]]; then
  create_python_environment metal "$requirements_dir/metal.in" "$requirements_dir/metal.lock.txt"
  echo "Metal profile created at $repo_root/.venv/metal"
  exit 0
fi

create_python_environment cpu "$requirements_dir/cpu.in" "$requirements_dir/cpu.lock.txt"

# SPheno
spheno_archive="$source_dir/SPheno-4.0.5.tar.gz"
if [[ ! -f "$spheno_archive" ]]; then
  curl --fail --location --retry 3 --output "$spheno_archive" "$(source_value spheno url)"
fi
record_archive_hash spheno "$spheno_archive"
spheno_source="$source_dir/SPheno-4.0.5"
if [[ ! -d "$spheno_source" ]]; then tar -xzf "$spheno_archive" -C "$source_dir"; fi
make -C "$spheno_source" F90=gfortran
mkdir -p "$install_dir/spheno/bin"
find "$spheno_source" -type f -name SPheno -perm -111 -exec cp {} "$install_dir/spheno/bin/SPheno" \; -quit

# micrOMEGAs
micro_source="$source_dir/micromegas"
clone_at_revision micromegas "$micro_source"
micro_patch="$repo_root/patches/micromegas-gcc16.patch"
if rg -q 'char\* alias\[10\]\[10\];' "$micro_source/CalcHEP_src/c_source/dynamicME/dynamic_cs.c"; then
  git -C "$micro_source" apply "$micro_patch"
fi
cat > "$micro_source/CalcHEP_src/FlagsForSh" <<'EOF'
# Seed CalcHEP with Homebrew GCC rather than Apple's clang: micrOMEGAs 6.0
# selects a GCC-specific extended numeric type on macOS.
CC="gcc-16"
CFLAGS="-g -fsigned-char -std=gnu99 -fPIC -Wno-error=incompatible-pointer-types"
HX11=
LX11="-lX11"
lDL="-ldl"
SHARED="-dynamiclib"
SONAME="-install_name "
SO=so
SNUM=
FC="gfortran"
FFLAGS="-fno-automatic"
lFort="-lgfortran"
CXX="g++-16"
CXXFLAGS="-g -fPIC"
RANLIB="ranlib -c"
MAKE=make
lQuad="-lquadmath"
export CC CFLAGS lDL LX11 SHARED SONAME SO FC FFLAGS RANLIB CXX CXXFLAGS lFort lQuad MAKE
EOF
CC=gcc-16 CXX=g++-16 make -C "$micro_source"
mkdir -p "$install_dir/micromegas/lib"
find "$micro_source" -type f -name 'micromegas.a' -exec cp {} "$install_dir/micromegas/lib/libmicromegas.a" \; -quit

# HiggsTools
higgs_source="$source_dir/higgstools"
clone_at_revision higgstools "$higgs_source"
cmake -S "$higgs_source" -B "$build_dir/higgstools" \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_INSTALL_PREFIX="$install_dir/higgstools" \
  -DBUILD_TESTING=OFF \
  -DCMAKE_POLICY_VERSION_MINIMUM=3.5 \
  -DCMAKE_CXX_FLAGS="-Wno-error=deprecated-declarations -Wno-error=deprecated-literal-operator" \
  -DCMAKE_OSX_ARCHITECTURES=arm64
cmake --build "$build_dir/higgstools" --parallel
cmake --install "$build_dir/higgstools"

# BSMPT: build against the project-local Homebrew dependency set. ConanCenter
# currently denies anonymous package reads, so we deliberately do not depend on
# a global Conan configuration or account credentials here.
bsmpt_source="$source_dir/bsmpt"
clone_at_revision bsmpt "$bsmpt_source"
gsl_prefix="$(brew --prefix gsl)"
bsmpt_package_dir="$build_dir/bsmpt-homebrew-packages/GSL"
mkdir -p "$bsmpt_package_dir"
cat > "$bsmpt_package_dir/GSLConfig.cmake" <<EOF
set(GSL_FOUND TRUE)
if(NOT TARGET GSL::gsl)
  add_library(GSL::gsl SHARED IMPORTED)
  set_target_properties(GSL::gsl PROPERTIES
    IMPORTED_LOCATION "$gsl_prefix/lib/libgsl.dylib"
    INTERFACE_INCLUDE_DIRECTORIES "$gsl_prefix/include"
    INTERFACE_LINK_LIBRARIES "$gsl_prefix/lib/libgslcblas.dylib")
endif()
EOF
cmake -S "$bsmpt_source" -B "$build_dir/bsmpt" \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_PREFIX_PATH="$brew_prefix/opt/eigen;$brew_prefix/opt/nlopt;$brew_prefix/opt/nlohmann-json;$build_dir/bsmpt-homebrew-packages" \
  -DCMAKE_OSX_ARCHITECTURES=arm64 \
  -DUseLibCMAES=OFF \
  -DUseNLopt=ON \
  -DBSMPTBuildExecutables=ON \
  -DBUILD_TESTING=OFF
# The upstream standalone examples link a test-only target when BUILD_TESTING
# is disabled. Build the supported BSMPT program itself for this install-only
# profile instead of the optional example suite.
cmake --build "$build_dir/bsmpt" --target BSMPT --parallel
mkdir -p "$install_dir/bsmpt"
bsmpt_binary="$(find "$build_dir/bsmpt" -type f -perm -111 -name BSMPT -print -quit)"
[[ -n "$bsmpt_binary" ]] || { echo "BSMPT build did not produce a BSMPT executable." >&2; exit 1; }
cp "$bsmpt_binary" "$install_dir/bsmpt/BSMPT"

# MultiNest
multinest_source="$source_dir/multinest"
clone_at_revision multinest "$multinest_source"
macos_sdk="$(xcrun --show-sdk-path)"
FC="$brew_prefix/bin/gfortran" cmake -S "$multinest_source" -B "$build_dir/multinest" \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_INSTALL_PREFIX="$install_dir/multinest" \
  -DCMAKE_POLICY_VERSION_MINIMUM=3.5 \
  -DCMAKE_Fortran_FLAGS="-fallow-argument-mismatch" \
  -Dm="$macos_sdk/usr/lib/libm.tbd" \
  -DCMAKE_OSX_ARCHITECTURES=arm64
# MultiNest's static/shared/MPI Fortran targets emit identically named module
# files into the source tree, so parallel targets can race on macOS.
cmake --build "$build_dir/multinest" --parallel 1
cmake --install "$build_dir/multinest"

echo "CPU profile installed. Run scripts/verify-install.sh --profile cpu"
