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
The installer fills archive SHA-256 values on its first successful download; commit
that manifest change to preserve the resulting local source lock.

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
- Re-run the appropriate bootstrap and verification scripts.
- Review and commit the updated manifest checksum and generated lockfile.
- Do not commit `third_party/`, `.venv/`, data, outputs, generated models, or secrets.

The stable CPU profile uses Python 3.12 because current JAX releases require
Python 3.12 or newer. The optional Metal profile follows Apple's experimental
`jax-metal` compatibility guidance and may have feature limitations.

BSMPT is built against Homebrew Eigen, GSL, NLopt, and nlohmann-json. Its
upstream Conan setup is intentionally not used because ConanCenter currently
rejects anonymous dependency downloads; the bootstrap keeps this alternative
fully local and does not require a Conan account.

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
