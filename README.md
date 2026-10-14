# Routing numerical contracts

We compare numerical contracts for routing solution evaluation, with mamut-routing-lib 0.11.0 and 0.12.0 as a case study. The experiments distinguish implementation conformance, fidelity to declared finite inputs, incumbent ranking and computational cost. The accompanying research report supports a reviewed contract decision for v0.13 and discusses integer scaling, rational arithmetic and other alternatives.

## Reproduce the published evidence

Use Python 3.11 or newer and [uv](https://docs.astral.sh/uv/). Commands run from this repository root. The package is installed in editable mode by `uv sync`, keeping its frozen sources and evidence alongside the Python modules.

The experiment package requires the repository's data and vendor trees. If running an installed package from elsewhere, set `NCCI_ROOT` to this checkout. External corpus commands accept `--data-root`, or use `MAMUT_ROUTING_ROOT` as their default. The bundled original solution fixture is the default source for original-panel materialization.

```bash
uv sync --locked
uv run python -m ncci.bundle restore
uv run pytest -q
uv run python scripts/conformance.py
uv run python -m ncci.history --from-bundle
uv run python -m ncci.analyze --report-dir report
uv run python -m ncci.report_study --report-dir report
```

The archives restore the materialized original and broader TD panels and all s108 route-level result records. Their SHA-256 digests, input manifests, result manifests and untouched upstream source hashes are checked by `ncci.bundle`. No external benchmark checkout is needed for these commands. Full-corpus materialized inputs are not bundled, so repeating the original full-corpus evaluations requires the pinned external artifacts. Report compilation additionally requires pdflatex, latexmk and biber:

```bash
latexmk -pdf -interaction=nonstopmode -halt-on-error -cd report/main.tex
```

## Repeat the controlled measurements

Run each command serially on an otherwise idle machine. The TD command includes frozen full-checker evaluations, preloaded route-fold kernels and a bounded rational comparison. The static command measures operand conversion, reduction and candidate comparison separately. Timing output is host-specific and replaces the local result file. Numerical results are validated before timings are accepted.

```bash
uv run routing-contracts td
uv run routing-contracts static
```

Higher precision, interval/adaptive arithmetic and explicit segment semantics are discussed in the report, not implemented here. Python integer timings concern arbitrary-size integers with a separate signed-64-bit eligibility check. They are not native fixed-width solver benchmarks. The rational TD reference uses an independent partitioning algorithm, so its time comparison includes both arithmetic and algorithmic differences.

## External source investigation

`manifests/data-repositories.json` records the original corpus pins. To rebuild the static candidate dataset, prepare a MAMUT-routing checkout at the recorded revisions with its benchmark repositories and sidecars, then run:

```bash
uv run python -m ncci.history --data-root /path/to/MAMUT-routing
```

The collector reads available BKS history, requires byte-identical instance artifacts, validates historical route sets with the frozen checker, and retains missing or changed-instance cases in coverage. `data/static-history.json.gz` provides consumed arc operands, serialized routes, historical declared costs, BKS byte hashes and candidate identifiers for repeating the numerical comparison without full matrices. `ncci.wave --data-root /path/to/MAMUT-routing` independently inventories the pinned cost, route and optimality-metadata changes. No command writes to a production checker, benchmark incumbent or solver environment. Personal discussions and the private audit ledger are excluded.

## Repository contents

- `src/ncci`: frozen-contract harnesses, independent rational oracle, static diagnostics, candidate-history comparison and controlled measurements.
- `vendor`: untouched released sources with upstream MIT licenses and per-file hashes.
- `fixtures` and `data`: diagnostic fixtures, compact materialized panels, candidate operands and archived route results.
- `manifests` and `results`: source identities, coverage, digests, comparisons and raw timings.
- `report`: LaTeX source, bibliography, generated tables, standalone figures and the compiled research report.

The local Nix shell extends `/home/onyr/nix-dev-base` and uses its pinned nixpkgs. Enter with `nix develop path:./nix-dev`. On another machine, use the portable uv instructions above or override the base input with your own copy. Nix is optional for numerical reproduction.

## Licensing and provenance

Original experiment code is MIT, copyright Florian Rascoussier. Retained mamut-routing-lib code carries its upstream MIT notice. Benchmark data have separate terms and provenance, including ODbL for OpenStreetMap-derived collections. See [DATA-LICENSES.md](DATA-LICENSES.md) and `data/licenses`. Exact arithmetic refers to explicitly declared finite inputs, not recovery of ideal road geometry or unrounded benchmark data.
