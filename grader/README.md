# Grader

Black-box testing suite that scores a participant's `eclass-mcp-server`
submission: it applies the patch on a fresh test branch, runs the rubric
against a separately-installed grading environment, and writes a JSON
results artefact.

## Overview

The grader scores a submission against a 100-point rubric of 90 atomic
rows, 30 to the Python implementation and 70 to the C replica.
[SCORING.md](SCORING.md) is the rubric itself: every row and its points,
the baseline-versus-feature split, and the per-section budget asserted at
import. The participant workspace ships separately from
[`bsc-apm-case-study-task`](https://github.com/sdi2200262/bsc-apm-case-study-task);
the grader probes its endpoints, resets its seed, and spawns participant
MCP servers under environment variables from its install prefix.

The package is layered `environment -> protocol -> scoring -> report`;
each layer's `__init__` documents its role and dependency direction.

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

The grading environment ships as per-architecture release tarballs from
`bsc-apm-case-study-task`; install it and bring it up before grading (see
that repository's
[INSTALL.md](https://github.com/sdi2200262/bsc-apm-case-study-task/blob/main/docs/INSTALL.md)).

## Quick start

```bash
# Bring the grading environment up
~/.bsc-apm/install
~/.bsc-apm/scripts/up

# Grade a patch (or --no-patch for the baseline)
python -m grader /path/to/solution.patch \
    --eclass-dir /path/to/eclass-mcp-server --mock-root ~/.bsc-apm

# Emit the rubric schema once, then browse a results JSON against it
python -m grader --schema -o /path/to/output-dir
./inspect.py /path/to/grader_results.json --schema /path/to/grader_schema.json

# Attach a note, or list every option
python -m grader.notes add /path/to/results-dir --test-id C.5.2 --note "..."
python -m grader --help
```

## How it works

On each run the grader probes the environment's HTTP endpoints, resets
the seed to baseline, applies the patch on a fresh branch, and provisions
the documented `.env` and `certs/` into the checkout. It then runs the
Python groups, gates the C side on the `make c-server` compile (C.1.1),
and runs the C stack, configuration, announcement, and valgrind memory
groups. SCORING.md covers the rows and their gating; the `protocol` layer
carries the assertion detail.

Two wiring mechanisms stay separate: the grader reads the environment's
own `grader-env/seed/seed.yaml`, so the expected values cannot drift from
the environment under test, while the `.env`/`certs/` copy guarantees the
participant server runs with the literal documented wiring.

The results JSON carries each row's per-submission outcome only (verdict,
credited points, message, captured output). The static rubric metadata,
the point maxima, categories, and descriptions, lives once in
`grader_schema.json` (`--schema`), which `inspect.py` joins to render the
descriptive views. Scored verdicts are reproducible against the pinned
references below, but `full_output` is not byte-stable across seedings:
announcement dates are written relative to the seeding wall clock and the
`ldd` capture includes loader addresses, so compare on verdicts, not by
byte diff.

## Compact serialization

The grader emits JSON-RPC through `json.dumps` (a space after each `,`
and `:`); the reference Python server emits compact. That whitespace is
insignificant under
[RFC 8259 §2](https://www.rfc-editor.org/rfc/rfc8259#section-2) and the
JSON-RPC / MCP stdio framing, so a conformant parser accepts both forms.
`--compact-json` emits every frame compact and writes
`grader_results_compact_serialization.json` beside the canonical report,
recording how a sound-but-compact-only replica would score.

## Pinned references

| Component | Pinned at |
|---|---|
| `eclass-mcp-server` | commit `dbd2d16` on `main` |
| Grading environment (amd64) | `bsc-apm-case-study-task` release tag |
| Grading environment (arm64) | `bsc-apm-case-study-task-arm64` release tag |

## Related

- [bsc-apm-case-study-task](https://github.com/sdi2200262/bsc-apm-case-study-task): the participant workspace and task specification.
- [../parser/](../parser/): the Claude Code transcript parser.
- [../pipeline/](../pipeline/): the submission processing pipeline.
- [SCORING.md](SCORING.md): the rubric the grader implements.
