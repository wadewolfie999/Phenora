# Phenora

Reproducible HEP-phenomenology toolchain for Apple-silicon macOS.

## Toolchain

| Component | Version |
| --- | --- |
| Python (CPU) | 3.12.14 |
| Python (Metal) | 3.11.16 |
| SPheno | 4.0.7 |
| micrOMEGAs | 7.1.4 |
| SModelS (CPU and Metal) | 3.2.0 |
| SModelS external tools | Pythia 6.4.27 / 8.317; NLL-fast 1.2 / 2.1 / 3.1; Resummino 3.1.2 |
| SModelS PDF support | LHAPDF 6.5.5; PDF4LHC21_40 |
| HiggsTools | v1.2 |
| BSMPT | 3.2.0 |
| MultiNest | v3.10 |
| dynesty | 3.1.0 |
| JAX (CPU) | 0.11.1 |
| JAX (Metal) | 0.4.30 |
| jax-metal | 0.1.0 |
| JAXNS | 2.6.9 |
| GetDist | 1.7.7 |

## Setup

Run CPU setup before Metal setup. CPU builds the shared SModelS external tools
using Homebrew GCC 16/GFortran, Boost, CMake, and GSL; Metal reuses that bundle.
Bootstrap installs missing prerequisites without requesting upgrades. Full
bootstrap recreates the selected Python environment.

```bash
scripts/bootstrap-macos.sh --profile cpu
scripts/verify-install.sh --profile cpu
```

```bash
scripts/bootstrap-macos.sh --profile metal
scripts/verify-install.sh --profile metal
```

Source revisions (where applicable), archive checksums, release pages, and citations: [`tooling/tools.json`](tooling/tools.json).

### Adding SModelS to existing environments

This focused installer preserves the environments and does not rebuild other
native tools. Both hashed locks pin SModelS while retaining their existing JAX
and unrelated package versions.

```bash
scripts/install-smodels.sh --profile cpu
scripts/install-smodels.sh --profile metal
scripts/verify-install.sh --profile cpu
scripts/verify-install.sh --profile metal
.venv/cpu/bin/python scripts/verify-smodels.py --native
.venv/metal/bin/python scripts/verify-smodels.py
```

Bootstrap and ordinary verification never download, resume, or load the SModelS
official experimental database. Ordinary verification checks the package version
and imports, CLIs, provenance, and linked external tools. The CPU profile also
runs database-free native smoke tests; Metal reuses the verified native bundle.

[SModelS 3.2.0](https://github.com/SModelS/smodels/releases/tag/3.2.0) is a
published stable release at revision `53a19a64c4c7d0bf3e9129d647091bba49c5e405`.
The official PyPI source archive is checked against both published MD5 and
SHA-256 values before extraction into ignored `third_party/src/smodels-3.2.0`.
External sources and their downloads are retained separately. The versioned
bundle at `third_party/install/smodels-3.2.0` is activated only after its native
build succeeds and `PROVENANCE.json` is written and verified. Each environment's
SModelS package links to that shared bundle; its original `lib` is retained as
`lib.pre-phenora`. Paths embedded in the native libraries make this installation
workspace-specific; rebuild it if the workspace moves.

External download URLs, observed SHA-256 values, compiler paths, and executable
hashes are recorded in the ignored provenance marker. The external hashes are
local integrity records, **not independently verified publisher checksums**.
Resummino uses C++17 and `patches/resummino-arm64.patch` to resolve scalar-complex
constructor and gather support defects in its bundled Fastor on ARM64. The
patch checksum is recorded in provenance; the downloaded archive is unchanged.
On case-insensitive filesystems, two uppercase Resummino translation units gain
a `.phenora-case.cc` suffix so both case-distinct upstream files are compiled.
Those filename mappings are also recorded in provenance.

CPU native smoke tests exercise Pythia 6/8 cross sections and all NLL-fast
energies, Resummino LO cross sections, the Fastor patch regression, and LHAPDF
command-line checks. They are not precision physics validation of the external
programs. Logs and validation summaries remain under
`third_party/build/smodels-<profile>-*`.

### Deferred IDM validation (explicit opt-in)

Database-backed IDM validation is deferred and has not passed. Run it later,
when needed for an actual HEP-phenomenology computation:

```bash
.venv/cpu/bin/python scripts/verify-smodels.py --idm-database
# Optional: validate the same sample in the Metal environment, reusing the cache.
.venv/metal/bin/python scripts/verify-smodels.py --idm-database
```

Only this explicit flag permits downloading or resuming the compatible official
database and running the supplied IDM SLHA/QNUMBERS sample. The inspected
[official320 metadata](https://smodels.github.io/database/official320) specifies
**1,164,931,032 bytes (~1.16 GB / 1.08 GiB)** and publisher SHA-1
`6152566677fa2d899577ba365097d289911414bf` for the
[Zenodo database artifact](https://zenodo.org/records/22255446/files/official320.pcl).
The opt-in command caches the metadata and resumes bounded byte-range downloads
under `third_party/cache/smodels`. It verifies the full size and published SHA-1
before loading the database, then records an observed SHA-256 in
`DATABASE-PROVENANCE.json`. That SHA-256 is a local integrity record, not an
independently published checksum. Completed cached data is rechecked before use;
the cached snapshot is not automatically refreshed. Allow space for the database,
temporary download chunk, and test output.

The interrupted partial download is preserved in the ignored cache and is not
used or resumed by installation or ordinary verification. A future opt-in run
must still finish and pass all checks; current installation success does not
claim database-backed scientific validation. The test will require successful
decomposition and finite experimental results and record the actual database
version, parameters, and logs in its ignored output directory.

Use `.venv/<profile>/bin/runSModelS.py` and `smodelsTools.py` for SModelS.
The opt-in IDM test selects pyhf's NumPy backend in both profiles and does not require
JAX or Metal acceleration. Metal device validation remains opt-in through
`PHENORA_VALIDATE_METAL_DEVICE=1 scripts/verify-install.sh --profile metal`.

micrOMEGAs 7.1.4 uses the existing macOS GCC 16 build flags without the older
GCC patch. Its v6.0 and 7.1.1 source trees and rollback libraries remain retained
under `third_party/src` and `third_party/install/micromegas-*-backup`.
