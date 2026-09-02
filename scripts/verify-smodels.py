#!/usr/bin/env python3
"""Verify SModelS without downloading or loading an experimental database.

Invoke with the selected profile's Python; --native adds CPU cross-section
smoke tests. Only --idm-database opts into the large official database and IDM
validation. Downloaded files and test evidence remain ignored.
"""

import argparse
import ast
import configparser
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SPEC = json.loads((ROOT / "tooling/tools.json").read_text())["python"]["smodels"]
SOURCE = ROOT / "third_party/src" / f"smodels-{SPEC['version']}"


def checksum(path, algorithm):
    value = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def prepare_database(cache):
    """Pin a verified official database snapshot locally before unpickling it."""
    with (cache / "database.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Another SModelS database download is running; retry after it finishes")
        return prepare_database_locked(cache)


def prepare_database_locked(cache):
    metadata = cache / "official-metadata.json"
    endpoint = "https://smodels.github.io/database/official320"
    if not metadata.exists():
        response = subprocess.check_output(["curl", "-fsSL", "--retry", "3",
                                            "--retry-all-errors", "--max-time", "90", endpoint])
        info = json.loads(response)
        if not info["url"].startswith("https://zenodo.org/") or not re.fullmatch(r"[0-9a-f]{40}", info["sha1"]):
            raise RuntimeError("Unexpected official database metadata")
        metadata.write_bytes(response)
    info = json.loads(metadata.read_text())
    target = cache / "official320.pcl"
    partial = target.with_suffix(".pcl.part")
    if target.exists() and (target.stat().st_size != info["size"]
                            or checksum(target, "sha1") != info["sha1"]):
        if partial.exists():
            raise RuntimeError("Both an invalid database and a partial download exist; inspect the cache")
        target.rename(partial)
    if not target.exists():
        print(f"Fetching official database ({info['size']} bytes); resumable cache: {partial}", flush=True)
        # Bounded ranges survive proxies that interrupt long streaming responses.
        chunk = cache / "official320.pcl.chunk"
        headers = cache / "official320.headers"
        while (partial.stat().st_size if partial.exists() else 0) < info["size"]:
            start = partial.stat().st_size if partial.exists() else 0
            end = min(start + 16 * 1024 * 1024, info["size"]) - 1
            response = subprocess.check_output([
                "curl", "-fsSL", "--retry", "3", "--retry-all-errors", "--connect-timeout", "30",
                "--max-time", "180", "--speed-limit", "1024", "--speed-time", "45",
                "--range", f"{start}-{end}", "--dump-header", headers,
                "--output", chunk, "--write-out", "%{http_code}", info["url"]], timeout=780)
            expected = f"content-range: bytes {start}-{end}/{info['size']}"
            if (response.strip() != b"206" or expected not in headers.read_text().lower().splitlines()
                    or chunk.stat().st_size != end - start + 1):
                raise RuntimeError("Database server did not return the requested byte range")
            with partial.open("ab") as destination, chunk.open("rb") as source:
                shutil.copyfileobj(source, destination)
            print(f"Database cached: {end + 1}/{info['size']} bytes", flush=True)
        chunk.unlink(missing_ok=True)
        if partial.stat().st_size != info["size"] or checksum(partial, "sha1") != info["sha1"]:
            raise RuntimeError("Official database size/SHA-1 mismatch; refusing to load it")
        partial.replace(target)
    record = {"metadata_url": endpoint, **info, "sha256_observed": checksum(target, "sha256")}
    (cache / "DATABASE-PROVENANCE.json").write_text(json.dumps(record, indent=2) + "\n")
    return target, record


def finite(value):
    if isinstance(value, float) and not math.isfinite(value):
        raise RuntimeError(f"Nonfinite numerical output: {value}")
    if isinstance(value, dict):
        for item in value.values():
            finite(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            finite(item)


def native_worker():
    from smodels.base.physicsUnits import pb
    from smodels.tools.pythia6Wrapper import Pythia6Wrapper
    from smodels.tools.pythia8Wrapper import Pythia8Wrapper
    from smodels.tools.nllFastWrapper import nllFastTools

    sample = str(SOURCE / "inputFiles/slha/simplyGluino.slha")
    results = {}
    for wrapper in (Pythia6Wrapper, Pythia8Wrapper):
        tool = wrapper()
        tool.maycompile = False
        tool.nevents = 20
        tool.sqrts = 13
        values = [float(x.value.asNumber(pb)) for x in tool.run(sample)]
        finite(values)
        if not values or not any(x > 0 for x in values):
            raise RuntimeError(f"{tool.name}: no positive cross section")
        results[tool.name + "_pb"] = values
    for energy, tool in nllFastTools.items():
        tool.maycompile = False
        values = tool.getKfactorsFor((1000021, 1000021), sample)
        if not values or any(x is None or not math.isfinite(x) or x <= 0 for x in values):
            raise RuntimeError(f"NLL-fast {energy} TeV: invalid K factors: {values}")
        results[f"nllfast_{energy}TeV"] = values
    lib = ROOT / SPEC["install_prefix"] / "smodels/lib"
    subprocess.run([lib / "resummino/resummino_install/bin/resummino", "-h"], check=True, timeout=30)
    subprocess.run([lib / "resummino/lhapdf/bin/lhapdf-config", "--version"], check=True, timeout=30)
    card = (SOURCE / "smodels/etc/input_resummino.in").read_text()
    replacements = {"slha": str(SOURCE / "inputFiles/slha/lightEWinos.slha"),
                    "particle1": "1000023", "particle2": "1000024",
                    "precision": "0.05", "max_iters": "5"}
    for key, value in replacements.items():
        card, count = re.subn(rf"(?m)^{key}\s*=.*$", f"{key} = {value}", card)
        if count != 1:
            raise RuntimeError(f"Unexpected Resummino input card: {key}")
    with tempfile.TemporaryDirectory(prefix="smodels-resummino-") as directory:
        directory = Path(directory)
        include = lib / "resummino/resummino-3.1.2/external/include"
        subprocess.run(["g++-16", "-std=c++17", f"-I{include}",
                        ROOT / "scripts/smodels-fastor-smoke.cc", "-o", directory / "fastor-smoke"],
                       check=True, timeout=60)
        subprocess.run([directory / "fastor-smoke"], check=True, timeout=30)
        (directory / "smoke.in").write_text(card)
        subprocess.run([lib / "resummino/resummino_install/bin/resummino", "--lo",
                        "--output", directory / "result.json", directory / "smoke.in"],
                       cwd=directory, check=True, timeout=180)
        result = json.loads((directory / "result.json").read_text())
        finite(result)
        if result["lo"] <= 0:
            raise RuntimeError("Resummino produced no positive LO cross section")
        results["resummino_lo"] = result
    print(json.dumps(results, indent=2))


def installation_checks():
    subprocess.run([sys.executable, ROOT / "scripts/smodels-toolchain.py", "verify"], check=True)
    for command, option in (("smodels-config", "-v"), ("runSModelS.py", "-h"), ("smodelsTools.py", "-h")):
        subprocess.run([Path(sys.prefix) / "bin" / command, option],
                       stdout=subprocess.DEVNULL, check=True, timeout=60)
    print(f"SModelS {SPEC['version']}: package, provenance, external links, and CLIs passed", flush=True)


def idm_validation(output):
    sample = SOURCE / "inputFiles/slha/idm_example.slha"
    cache = ROOT / "third_party/cache/smodels"
    cache.mkdir(parents=True, exist_ok=True)
    database, database_record = prepare_database(cache)
    parameters = configparser.ConfigParser()
    parameters.read(SOURCE / "smodels/etc/parameters_default.ini")
    # The IDM QNUMBERS, not the default MSSM particle definitions, define this model.
    parameters.set("particles", "model", str(sample))
    parameters.set("options", "pyhfbackend", "numpy")
    parameters.set("printer", "outputType", "python,summary")
    parameters.set("database", "path", str(database))
    with (output / "parameters.ini").open("w") as handle:
        parameters.write(handle)
    env = os.environ.copy()
    env["SMODELS_CACHEDIR"] = str(cache)
    with (output / "idm.log").open("w") as log:
        subprocess.run([Path(sys.prefix) / "bin/runSModelS.py", "-f", sample,
                        "-p", output / "parameters.ini", "-o", output, "-d", "-T", "300"],
                       cwd=output, env=env, stdout=log, stderr=subprocess.STDOUT,
                       timeout=1800, check=True)
    tree = ast.parse((output / "idm_example.slha.py").read_text())
    assignments = [node for node in tree.body if isinstance(node, ast.Assign)
                   and any(isinstance(target, ast.Name) and target.id == "smodelsOutput"
                           for target in node.targets)]
    if len(assignments) != 1:
        raise RuntimeError(f"Missing SModelS structured output; inspect {output}")
    result = ast.literal_eval(assignments[0].value)
    finite(result)
    status = result["OutputStatus"]
    if (status["file status"] != 1 or status["decomposition status"] != 1
            or status["smodels version"] != SPEC["version"]):
        raise RuntimeError(f"IDM sample did not succeed: {status}")
    ratios = [entry["r"] for entry in result.get("ExptRes", []) if entry.get("r") is not None]
    if not ratios or any(not isinstance(r, (int, float)) or r < 0 for r in ratios):
        raise RuntimeError("IDM sample produced no valid experimental r values")
    report = {"version": SPEC["version"], "profile": Path(sys.prefix).name,
              "database": status["database version"], "status": status,
              "database_provenance": database_record,
              "finite_r_values": len(ratios), "maximum_r": max(ratios)}
    return report


def main(native=False, idm_database=False):
    installation_checks()
    if not native and not idm_database:
        print("Official-database IDM validation deferred; opt in with --idm-database")
        return
    build = ROOT / "third_party/build"
    build.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix=f"smodels-{Path(sys.prefix).name}-", dir=build))
    print(f"SModelS test evidence: {output}", flush=True)
    report = {"version": SPEC["version"], "profile": Path(sys.prefix).name,
              "idm_database_validation": "deferred (not requested)"}
    if native:
        with (output / "native.log").open("w") as log:
            subprocess.run([sys.executable, __file__, "--native-worker"], cwd=output,
                           stdout=log, stderr=subprocess.STDOUT, timeout=600, check=True)
        report["native_smoke"] = "passed (Pythia6/8, NLL-fast7/8/13, Resummino LO, LHAPDF version)"
    if idm_database:
        report.update(idm_validation(output))
        report["idm_database_validation"] = "passed"
    (output / "validation.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native", action="store_true", help="run database-free CPU-native smoke tests")
    parser.add_argument("--idm-database", action="store_true",
                        help="opt in to download/resume the ~1.16 GB official database and run IDM validation")
    parser.add_argument("--native-worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.native_worker:
        native_worker()
    else:
        main(args.native, args.idm_database)
