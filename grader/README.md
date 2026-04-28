# Grader

Black-box testing suite for evaluating participant submissions
against the pinned `eclass-mcp-server` baseline. The grader applies
a participant's patch on a fresh test branch, runs the rubric
phases against a separately-installed testing environment, and
writes a JSON results artefact the pipeline promotes into the
dataset.

## Overview

The grader scores a participant's submission against a 100-point
rubric covering Python baseline preservation (12 points), Python
features (36 points), and the C replica (52 points). The baseline
score with no patch applied is 12/100. The participant testing
environment is shipped separately by the
[`bsc-apm-case-study-env`](https://github.com/sdi2200262/bsc-apm-case-study-env)
package; the grader probes its endpoints, invokes its reset script,
and spawns participant MCP servers under environment variables
derived from its install prefix.

## Quick start

```bash
# Bring the testing environment up (one-time install plus scripts/up)
~/.bsc-apm/install
~/.bsc-apm/scripts/up

# Test baseline (no patch)
python -m grader --no-patch \
    --eclass-dir /path/to/eclass-mcp-server \
    --mock-root ~/.bsc-apm

# Grade a patch file
python -m grader /path/to/solution.patch \
    --eclass-dir /path/to/eclass-mcp-server \
    --mock-root ~/.bsc-apm

# Browse a results JSON in the terminal
./inspect.py /path/to/results.json

# Full options
python -m grader --help
```

See [SETUP.md](SETUP.md) for the full grading-machine prerequisites
and testing-environment install instructions.

## Architecture

The grader interacts with a separately-installed testing
environment. On every grading run the grader probes the
environment's HTTP endpoints (`http://localhost/` for openeclass,
`https://localhost:8082/health` for the mock CAS), invokes
`<mock-root>/scripts/reset` to flush state between runs, then
sequences the phase modules:

1. Apply the patch on a fresh test branch (or skip in `--no-patch` baseline mode).
2. Python build (`uv sync` against the participant's checkout).
3. Python baseline phase (P1, P2, L1-L3, O1-O2, C1-C2, A1).
4. Python feature phase (AN1-AN6, GAN1-GAN6).
5. C build (`make c-server`).
6. Memory phase (Valgrind against the C replica).
7. C baseline phase and C feature phase (the same rubric items
   under the C implementation).

Phase failures are recorded in the results JSON without halting
the run. Patch-apply failures, pre-flight failures, and reset
failures terminate the run early.

## Directory structure

```
grader/
├── __init__.py
├── __main__.py                 # CLI entry: python -m grader
├── inspect.py                  # results browser
├── README.md
├── SETUP.md
└── src/
    ├── __init__.py
    ├── config.py               # path resolution from CLI flags or grader.yaml
    ├── errors.py               # GraderError hierarchy
    ├── preflight.py            # HTTP probes against the testing environment
    ├── reset.py                # subprocess invocation of scripts/reset
    ├── patch.py                # git apply / cleanup
    ├── build_python.py         # uv sync for the Python implementation
    ├── build_c.py              # make c-server for the C replica
    ├── memory.py               # Valgrind run against the C binary
    ├── scoring.py              # rubric definitions and the Scorer
    ├── reporting.py            # JSON, text, and console writers
    └── protocol/
        ├── __init__.py
        ├── runner.py           # server spawn, JSON-RPC framing, fixtures
        ├── baseline_tests.py   # baseline assertions (P*, L*, O*, C*, A*)
        ├── feature_tests.py    # feature assertions (AN*, GAN*)
        ├── python_baseline.py  # phase aggregator (impl=python)
        ├── python_feature.py   # phase aggregator (impl=python)
        ├── c_baseline.py       # phase aggregator (impl=c)
        └── c_feature.py        # phase aggregator (impl=c)
```

## Documentation

- [SETUP.md](SETUP.md): grading-machine prerequisites and the
  testing-environment install procedure.
- Source-code docstrings: detailed per-module documentation in
  `src/` and `src/protocol/`.

## Related

- [bsc-apm-case-study-env](https://github.com/sdi2200262/bsc-apm-case-study-env):
  the participant testing environment the grader runs against.
- [../parser/](../parser/): transcript parser for participant
  Claude Code session logs.
- [../pipeline/](../pipeline/): submission processing pipeline
  that orchestrates validation, grading, parsing, and dataset
  aggregation.
- [Task specification](../task/): submission requirements and the
  scoring rubric.
