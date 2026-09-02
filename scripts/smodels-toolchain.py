#!/usr/bin/env python3
"""Prepare, build, and expose the shared SModelS external tools."""

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SPEC = json.loads((ROOT / "tooling/tools.json").read_text())["python"]["smodels"]
VERSION = SPEC["version"]
SOURCE = ROOT / "third_party/src" / f"smodels-{VERSION}"
ARCHIVE = SOURCE.parent / f"smodels-{VERSION}.tar.gz"
INSTALL = ROOT / SPEC["install_prefix"]
LIB = INSTALL / "smodels/lib"
CACHE = SOURCE.parent / f"smodels-{VERSION}-external"
MARKER = INSTALL / "PROVENANCE.json"
RESUMMINO_PATCH = ROOT / "patches/resummino-arm64.patch"
DOWNLOAD_URLS = {
    "pythia8317.tgz": "https://pythia.org/releases/pythia83/pythia8317.tgz",
    "LHAPDF-6.5.5.tar.gz": "https://smodels.github.io/resummino/LHAPDF-6.5.5.tar.gz",
    "resummino-3.1.2.zip": "https://smodels.github.io/resummino/resummino-3.1.2.zip",
    "PDF4LHC21_40.tar.gz": "https://lhapdfsets.web.cern.ch/lhapdfsets/current/PDF4LHC21_40.tar.gz",
}
BINARIES = [
    "pythia6/pythia_lhe", "pythia8/pythia8.exe",
    "nllfast/nllfast-1.2/nllfast_7TeV", "nllfast/nllfast-2.1/nllfast_8TeV",
    "nllfast/nllfast-3.1/nllfast_13TeV", "resummino/resummino_install/bin/resummino",
    "resummino/lhapdf/bin/lhapdf-config",
]


def digest(path, algorithm="sha256"):
    h = hashlib.new(algorithm)
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def run(args, cwd=ROOT, env=None, capture=False):
    print("+", " ".join(map(str, args)), flush=True)
    return subprocess.run(list(map(str, args)), cwd=cwd, env=env, check=True,
                          text=True, stdout=subprocess.PIPE if capture else None)


def download(url, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    record = path.with_name(path.name + ".json")
    if path.exists() and record.exists():
        info = json.loads(record.read_text())
        if info["url"] != url or info["sha256"] != digest(path):
            raise RuntimeError(f"Cached download changed: {path}")
        return info
    if path.exists():
        raise RuntimeError(f"Unrecorded download already exists: {path}")
    partial = path.with_name(path.name + ".part")
    response = run(["curl", "--fail", "--location", "--retry", "3", "--retry-all-errors",
                    "--connect-timeout", "30", "--max-time", "900",
                    "--output", partial, "--write-out", "%{url_effective}", url], capture=True)
    info = {"url": url, "effective_url": response.stdout.strip(),
            "sha256": digest(partial), "size": partial.stat().st_size,
            "publisher_checksum_verified": False}
    partial.replace(path)
    record.write_text(json.dumps(info, indent=2) + "\n")
    return info


def check_source():
    for algorithm in ("md5", "sha256"):
        if digest(ARCHIVE, algorithm) != SPEC["source"][algorithm]:
            raise RuntimeError(f"SModelS {algorithm} mismatch: {ARCHIVE}")


def extract(archive, destination):
    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as z:
            for name in z.namelist():
                if not (destination / name).resolve().is_relative_to(destination.resolve()):
                    raise RuntimeError(f"Unsafe ZIP member: {name}")
            z.extractall(destination)
        restore_zip_modes(archive, destination)
    else:
        with tarfile.open(archive) as t:
            t.extractall(destination, filter="data")


def restore_zip_modes(archive, destination):
    # ZipFile extraction drops Unix executable bits needed by LoopTools configure.
    with zipfile.ZipFile(archive) as z:
        for member in z.infolist():
            path = destination / member.filename
            if not path.resolve().is_relative_to(destination.resolve()):
                raise RuntimeError(f"Unsafe ZIP member: {member.filename}")
            mode = (member.external_attr >> 16) & 0o777
            if mode:
                path.chmod(mode)


def restore_case_collisions(archive, destination):
    # These translation units differ only by case. macOS APFS commonly does not.
    mappings = {}
    with zipfile.ZipFile(archive) as z:
        groups = {}
        for name in z.namelist():
            if name.endswith(".cc"):
                groups.setdefault(name.casefold(), []).append(name)
        for names in groups.values():
            if len(names) < 2 or not (destination / names[0]).samefile(destination / names[-1]):
                continue
            for name in names[:-1]:
                original = destination / name
                target = original.with_name(original.stem + ".phenora-case.cc")
                content = z.read(name)
                if target.exists() and target.read_bytes() != content:
                    raise RuntimeError(f"Case-preserved source changed: {target}")
                target.write_bytes(content)
                mappings[name] = str(target.relative_to(destination))
    return mappings


def prepare():
    if not ARCHIVE.exists():
        download(SPEC["source"]["url"], ARCHIVE)
    check_source()
    if not SOURCE.exists():
        extract(ARCHIVE, SOURCE.parent)
    if (SOURCE / "smodels/version").read_text().strip() != VERSION:
        raise RuntimeError("Extracted SModelS version mismatch")


def check_bundle():
    info = json.loads(MARKER.read_text())
    if (info["version"] != VERSION or info["source"] != SPEC["source"]
            or info["external_tools"] != SPEC["external_tools"]):
        raise RuntimeError("SModelS installation provenance differs from the manifest")
    if info["patches"] != {RESUMMINO_PATCH.name: digest(RESUMMINO_PATCH)}:
        raise RuntimeError("Resummino build patch differs from installation provenance")
    for name in BINARIES:
        path = LIB / name
        if not os.access(path, os.X_OK) or digest(path) != info["binaries"][name]:
            raise RuntimeError(f"Missing or changed external executable: {path}")
    if set(info["downloads"]) != set(DOWNLOAD_URLS):
        raise RuntimeError("Incomplete external download provenance")
    for name, record in info["downloads"].items():
        if record["url"] != DOWNLOAD_URLS[name] or digest(CACHE / name) != record["sha256"]:
            raise RuntimeError(f"External source checksum mismatch: {name}")
    return info


def build():
    prepare()
    if MARKER.exists():
        check_bundle()
        print("Reusing verified SModelS external tools")
        return
    if not INSTALL.exists():
        shutil.copytree(SOURCE, INSTALL)
    if (INSTALL / "smodels/version").read_text().strip() != VERSION:
        raise RuntimeError("External-tool staging directory has an unexpected version")
    brew = Path(run(["brew", "--prefix"], capture=True).stdout.strip())
    env = os.environ.copy()
    env.update(CC=str(brew / "bin/gcc-16"), CXX=str(brew / "bin/g++-16"),
               FC=str(brew / "bin/gfortran"))
    jobs = str(min(4, os.cpu_count() or 1))
    # Build the bundled Fortran sources without invoking upstream pip upgrades.
    for directory in [LIB / "pythia6"] + [LIB / f"nllfast/nllfast-{v}" for v in SPEC["external_tools"]["nllfast"]]:
        run(["make", f"FCC={env['FC']}"], cwd=directory, env=env)

    downloads = {name: download(url, CACHE / name) for name, url in DOWNLOAD_URLS.items()}
    pythia = LIB / "pythia8/pythia8317"
    if not pythia.exists():
        extract(CACHE / "pythia8317.tgz", pythia.parent)
    if not (pythia / "lib/libpythia8.a").exists():
        run(["./configure", f"--cxx={env['CXX']}"], cwd=pythia, env=env)
        run(["make", f"-j{jobs}"], cwd=pythia, env=env)
    run([env["CXX"], "-O3", "-std=c++14", f"-I{pythia}/include",
         f"-I{pythia}/include/Pythia8", f"-L{pythia}/lib",
         f"-Wl,-rpath,{pythia}/lib", "-o", "pythia8.exe", "pythia8.cc", "-lpythia8", "-ldl"],
        cwd=pythia.parent, env=env)
    (pythia.parent / "xml.doc").write_text(str(pythia / "share/Pythia8/xmldoc") + "\n")

    res = LIB / "resummino"
    lha_source = res / "LHAPDF-6.5.5"
    lha_install = res / "lhapdf"
    if not lha_source.exists():
        extract(CACHE / "LHAPDF-6.5.5.tar.gz", res)
    if not (lha_install / "bin/lhapdf-config").exists():
        run(["./configure", f"--prefix={lha_install}", "--disable-python"], cwd=lha_source, env=env)
        run(["make", f"-j{jobs}"], cwd=lha_source, env=env)
        run(["make", "install"], cwd=lha_source, env=env)
    if not (lha_install / "share/LHAPDF/PDF4LHC21_40").exists():
        extract(CACHE / "PDF4LHC21_40.tar.gz", lha_install / "share/LHAPDF")
    res_source = res / "resummino-3.1.2"
    if not res_source.exists():
        extract(CACHE / "resummino-3.1.2.zip", res)
    restore_zip_modes(CACHE / "resummino-3.1.2.zip", res)
    case_mappings = restore_case_collisions(CACHE / "resummino-3.1.2.zip", res)
    patch_args = ["patch", "--batch", "-p1", "-i", str(RESUMMINO_PATCH)]
    test = subprocess.run(patch_args + ["--forward", "--dry-run"], cwd=res_source,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if test.returncode == 0:
        run(patch_args + ["--forward"], cwd=res_source)
    else:
        run(patch_args + ["--reverse", "--dry-run"], cwd=res_source)
    run(["cmake", "-S", res_source, "-B", res_source / "build-phenora",
         f"-DLHAPDF={lha_install}", f"-DCMAKE_INSTALL_PREFIX={res}/resummino_install",
         "-DCMAKE_POLICY_VERSION_MINIMUM=3.5", "-DCMAKE_OSX_ARCHITECTURES=arm64",
         f"-DCMAKE_CXX_COMPILER={env['CXX']}", f"-DCMAKE_C_COMPILER={env['CC']}",
         f"-DCMAKE_CXX_FLAGS=-I{brew}/opt/boost/include",
         "-DCMAKE_CXX_STANDARD=17", "-DCMAKE_CXX_STANDARD_REQUIRED=ON",
         f"-DCMAKE_Fortran_COMPILER={env['FC']}",
         f"-DCMAKE_PREFIX_PATH={brew}/opt/boost;{brew}/opt/gsl"], env=env)
    run(["cmake", "--build", res_source / "build-phenora", "--parallel", jobs], env=env)
    run(["cmake", "--install", res_source / "build-phenora"], env=env)
    # SModelS's Resummino wrapper also resolves this source-tree executable.
    (res_source / "bin").mkdir(exist_ok=True)
    if not (res_source / "bin/resummino").exists():
        (res_source / "bin/resummino").symlink_to(res / "resummino_install/bin/resummino")
    for name in BINARIES:
        if not os.access(LIB / name, os.X_OK):
            raise RuntimeError(f"Build did not produce {name}")
    run([LIB / "pythia8/pythia8.exe", "-h"])
    run([LIB / "resummino/resummino_install/bin/resummino", "-h"])
    info = {"version": VERSION, "source": SPEC["source"],
            "external_tools": SPEC["external_tools"], "downloads": downloads,
            "patches": {RESUMMINO_PATCH.name: digest(RESUMMINO_PATCH)},
            "case_preserved_sources": case_mappings,
            "compilers": {k: env[k] for k in ("CC", "CXX", "FC")},
            "binaries": {name: digest(LIB / name) for name in BINARIES}}
    pending = MARKER.with_suffix(".json.new")
    pending.write_text(json.dumps(info, indent=2) + "\n")
    pending.replace(MARKER)
    check_bundle()


def activate():
    prepare()
    check_bundle()
    import smodels
    if smodels.__version__ != VERSION or importlib.metadata.version("smodels") != VERSION:
        raise RuntimeError("Install the profile's SModelS lock before activation")
    package = Path(smodels.__file__).resolve().parent
    if not package.is_relative_to(Path(sys.prefix)):
        raise RuntimeError("SModelS must be installed in the selected virtual environment")
    target = package / "lib"
    if target.is_symlink():
        if target.resolve() == LIB.resolve():
            return
        raise RuntimeError(f"Unexpected existing SModelS library link: {target}")
    backup = package / "lib.pre-phenora"
    if target.exists():
        if backup.exists():
            raise RuntimeError(f"Refusing to overwrite package backup {backup}")
        target.rename(backup)
    target.symlink_to(LIB, target_is_directory=True)
    print(f"Activated SModelS {VERSION} external tools in {sys.prefix}")


def verify():
    check_source()
    check_bundle()
    import smodels
    if smodels.__version__ != VERSION or importlib.metadata.version("smodels") != VERSION:
        raise RuntimeError("Installed SModelS version mismatch")
    if (Path(smodels.__file__).parent / "lib").resolve() != LIB.resolve():
        raise RuntimeError("SModelS external tools are not linked to the verified bundle")
    if (SOURCE / "smodels/version").read_text().strip() != VERSION:
        raise RuntimeError("SModelS source reference version mismatch")
    print(f"SModelS {VERSION}: source hashes, provenance, package, and external binaries verified")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "build", "activate", "verify", "check_bundle"])
    args = parser.parse_args()
    try:
        globals()[args.action]()
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        sys.exit(str(error))
