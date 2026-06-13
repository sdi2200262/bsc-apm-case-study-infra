# Grader

Black-box testing suite that scores a participant's `eclass-mcp-server`
submission. It applies the patch on a fresh test branch, runs the rubric
against the grading environment, and writes a JSON results artefact.

## Overview

The grader scores a submission against a 100-point rubric of 90 atomic
rows, 30 to the Python implementation and 70 to the C replica.
[SCORING.md](SCORING.md) is the rubric itself, listing every row and its
points, the baseline-versus-feature split, and the per-section budgets.

It runs against the grading environment in [`../grader-env/`](../grader-env/),
a self-contained openeclass and mock CAS built and released from this
repository, and spawns the participant's MCP server against it. That
environment matches the participant package's openeclass pin but carries
a richer two-user seed for the rubric, so it diverges from the mock
participants used; the divergence is documented in `../grader-env/`.

The package is layered `environment -> protocol -> scoring -> report`,
and each layer's `__init__` documents its role and dependency direction.

## Prerequisites

Linux (native, WSL2, or a Linux VM on macOS), with Python 3.12+ and `uv`
on `PATH`, Docker Engine with Compose v2, and Git. The C tests also need
`gcc` (>= 9.0), `libcurl4-openssl-dev`, `libxml2-dev`, `pkg-config`,
`valgrind`, and `make`.

```bash
sudo apt-get install -y python3 git build-essential pkg-config \
    libcurl4-openssl-dev libxml2-dev valgrind
curl -fsSL https://get.docker.com | sudo sh
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Install and bring up the grading environment from [`../grader-env/`](../grader-env/)
before grading.

## Quick start

```bash
# Bring the grading environment up (see ../grader-env/)
~/.bsc-apm-grader-env/install
~/.bsc-apm-grader-env/scripts/up

# Grade the baseline (no patch)
python -m grader --no-patch \
    --eclass-dir /path/to/eclass-mcp-server \
    --mock-root ~/.bsc-apm-grader-env

# Grade a patch file
python -m grader /path/to/solution.patch \
    --eclass-dir /path/to/eclass-mcp-server \
    --mock-root ~/.bsc-apm-grader-env

# Emit the rubric schema once (the static per-row metadata)
python -m grader --schema -o /path/to/output-dir

# Browse a results JSON, joined against the schema
python -m grader.inspect /path/to/grader_results.json --schema /path/to/grader_schema.json

# Attach a free-prose note to a graded submission
python -m grader.notes add /path/to/results-dir \
    --test-id C.5.2 --note "context for the next reader"

# Full options
python -m grader --help
```

## How it works

On each run the grader probes the grading environment's HTTP endpoints,
resets its seed to baseline, applies the patch on a fresh branch, and
provisions the documented `.env` and `certs/` into the checkout. It then
runs the Python groups, gates the C side on the `make c-server` compile
(C.1.1), and runs the C stack, configuration, announcement, and valgrind
memory groups.
SCORING.md covers the rows and their gating, and the `protocol` layer
carries the assertion detail.

Two wiring mechanisms stay separate. The grader reads the environment's
own `../grader-env/seed/seed.yaml`, so the expected values cannot drift
from the environment under test, while the `.env`/`certs/` copy
guarantees the participant server runs with the literal documented
wiring.

The results JSON carries each row's per-submission outcome only (verdict,
credited points, message, captured output). The static rubric metadata,
the point maxima, categories, and descriptions, lives once in
`grader_schema.json` (`--schema`), which `inspect.py` joins to render the
descriptive views. Scored verdicts are reproducible against the pinned
references below, but `full_output` is not byte-stable across seedings,
because announcement dates are written relative to the seeding wall clock
and the `ldd` capture includes loader addresses. Compare on verdicts, not
by byte diff.

## Compact serialization

The grader emits JSON-RPC through `json.dumps` (a space after each `,`
and `:`); the reference Python server emits compact. That whitespace is
insignificant under
[RFC 8259 §2](https://www.rfc-editor.org/rfc/rfc8259#section-2) and the
JSON-RPC / MCP stdio framing, so a conformant parser accepts both forms.
`--compact-json` emits every frame compact and writes
`grader_results_compact_serialization.json` beside the canonical report,
recording how a sound-but-compact-only replica would score.

```bash
python -m grader /path/to/solution.patch \
    --eclass-dir /path/to/eclass-mcp-server \
    --mock-root ~/.bsc-apm-grader-env \
    --compact-json
```

## Pinned references

| Component | Pinned at |
|---|---|
| `eclass-mcp-server` | commit `dbd2d16` on `main` |
| Grading environment | `grader-env-amd64` / `grader-env-arm64` release tags (this repo) |

## Related

- [../grader-env/](../grader-env/): the openeclass and mock CAS the grader runs against.
- [../parser/](../parser/): the Claude Code transcript parser.
- [../pipeline/](../pipeline/): the submission processing pipeline.
- [bsc-apm-case-study-task](https://github.com/sdi2200262/bsc-apm-case-study-task): the participant workspace and task specification.
- [SCORING.md](SCORING.md): the rubric the grader implements.
