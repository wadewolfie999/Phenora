# phenora

A reproducible computational workspace for high-energy-physics phenomenology on
Apple-silicon macOS. It deliberately tracks only project-owned code,
documentation, manifests, and scripts. Downloaded upstream sources, compilers,
virtual environments, model files, data, and scan results stay local.

## Toolchain

| Tool | Role | Profile |
| --- | --- | --- |
| SPheno | spectrum and decay calculations | native CPU |
| micrOMEGAs | dark-matter observables | native CPU |
| HiggsTools | HiggsBounds/HiggsSignals successor | native CPU |
| BSMPT | electroweak phase transitions | native CPU |
| MultiNest | nested sampling | native CPU |
| dynesty | dynamic nested sampling | Python CPU |
| JAX | accelerated numerical computing | Python CPU / experimental Metal |
| JAXNS | JAX-based nested sampling | Python CPU |
| GetDist | posterior analysis and plotting | Python CPU |

Exact first-party source provenance is in [`tooling/tools.json`](tooling/tools.json).
The micrOMEGAs 7.1.1 archive is published by its authors in the
[official Zenodo record](https://zenodo.org/records/20547050) and is verified
against its recorded checksums before extraction.

## Setup

The default profile is the stable ARM64 CPU environment. It installs only missing
Homebrew formulae; it never upgrades unrelated packages.

```bash
scripts/bootstrap-macos.sh --profile cpu
scripts/verify-install.sh --profile cpu
```

The experimental Apple Metal environment is isolated from the CPU environment:

```bash
scripts/bootstrap-macos.sh --profile metal
scripts/verify-install.sh --profile metal
```

Activate an environment with `source .venv/cpu/bin/activate` or
`source .venv/metal/bin/activate`. Native tools install below
`third_party/install/`.

## Reproducibility and updates

- Change a pinned version/revision only in `tooling/tools.json` or the relevant
  `requirements/*.in` file.
- Regenerate the corresponding hash-pinned lockfile from public PyPI in a
  controlled resolver environment.
- Re-run the appropriate bootstrap and verification scripts. Bootstrap installs
  from the lockfile; the `*.in` files are resolver inputs, not installation
  inputs.
- Do not commit `third_party/`, `.venv/`, data, outputs, generated models, or secrets.

The stable CPU profile uses project-local Homebrew Python 3.12 with the latest
stable JAX/JAXLIB pair. The optional Metal profile remains isolated on the
Apple-documented Python 3.11 and `jax-metal` 0.1.0 baseline until a GPU-backed
validation run establishes a newer stack.

micrOMEGAs is installed from the authors' versioned 7.1.1 archive. The existing
`patches/micromegas-gcc16.patch` applies only to the preserved v6.0 source and is
not applied to 7.1.1, whose source does not accept those patch hunks.

BSMPT is built against Homebrew Eigen, GSL, NLopt, and nlohmann-json. Its
upstream Conan setup is intentionally not used because ConanCenter currently
rejects anonymous dependency downloads; the bootstrap keeps this alternative
fully local and does not require a Conan account.

The Metal package probe is safe on hosts without a usable GPU. Set
`PHENORA_VALIDATE_METAL_DEVICE=1` when an actual device-backed validation is
required.

## Citations

Citations and primary software references are linked in
[`tooling/tools.json`](tooling/tools.json). Cite each program according to its
upstream guidance in any research output that uses it.

## GitHub publication

After a reviewed initial commit, create and push the public repository with the
GitHub CLI:

```bash
gh auth login
gh repo create phenora --public --source=. --remote=origin --push
```

The repository name is created under the GitHub account authenticated in `gh`.
