# Phenora

Reproducible HEP-phenomenology toolchain for Apple-silicon macOS.

## Toolchain

| Component | Version |
| --- | --- |
| Python (CPU) | 3.12.14 |
| Python (Metal) | 3.11.16 |
| SPheno | 4.0.7 |
| micrOMEGAs | 7.1.1 |
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

```bash
scripts/bootstrap-macos.sh --profile cpu
scripts/verify-install.sh --profile cpu
```

```bash
scripts/bootstrap-macos.sh --profile metal
scripts/verify-install.sh --profile metal
```

Source revisions, archive checksums, and citations: [`tooling/tools.json`](tooling/tools.json).
