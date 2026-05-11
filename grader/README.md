# Grader

Black-box testing suite for evaluating participant submissions
against the pinned `eclass-mcp-server` baseline. The grader applies
a participant's patch on a fresh test branch, runs the rubric
phases against a separately-installed testing environment, and
writes a JSON results artefact the pipeline promotes into the
dataset.

## Overview

The grader scores a participant's submission against a 100-point
rubric covering the Python implementation (41 points: 10 baseline,
17 course announcements, 14 general announcements) and the C
replica (59 points: 5 build and tech-stack, 10 baseline, 17 course
announcements, 14 general announcements, 13 memory scenarios). The
baseline score with no patch applied is 9/100, awarded for the
nine Python baseline rows the upstream `eclass-mcp-server`
reference already passes; P.1.1 (the `tools/list` registration
check for all six tools) is the one baseline row that requires
the patch's tool additions to pass. The participant testing environment is shipped
separately by the
[`bsc-apm-case-study-task`](https://github.com/sdi2200262/bsc-apm-case-study-task)
repository; the grader probes its endpoints, invokes its reset script,
and spawns participant MCP servers under environment variables
derived from its install prefix.

## Prerequisites

**Operating system.** Linux (native, WSL2, or a Linux VM on macOS).

**Required software.**

- Python 3.10 or newer with `uv` on `PATH`.
- Docker Engine plus Compose v2 (consumed by the testing environment).
- Git.

**Required for the C tests.**

- `gcc` (>= 9.0 for C11 support).
- `libcurl4-openssl-dev` (libcurl >= 7.81.0).
- `libxml2-dev` (libxml2 >= 2.9.13).
- `valgrind`.
- `make`.

Ubuntu install lines:

```bash
sudo apt-get install -y python3 git build-essential \
    libcurl4-openssl-dev libxml2-dev valgrind
curl -fsSL https://get.docker.com | sudo sh
curl -LsSf https://astral.sh/uv/install.sh | sh
```

The Docker convenience script matches what the participant
package recommends to participants; the apt line covers the
remaining system dependencies. On non-Ubuntu hosts substitute the
equivalent package set.

## Testing environment

The `bsc-apm-case-study-task` repository ships per-architecture release
tarballs (amd64 and arm64); install instructions, lifecycle scripts,
and seed documentation live in that repository's
[INSTALL.md](https://github.com/sdi2200262/bsc-apm-case-study-task/blob/main/docs/INSTALL.md).
The grader expects the testing environment to be installed and
running before it is invoked.

## Quick start

```bash
# Bring the testing environment up (one-time install plus scripts/up;
# see the env package's INSTALL.md for the per-arch download).
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

# Attach a free-prose note to a graded submission
python -m grader.notes add /path/to/results-dir \
    --test-id C.5.2 --note "context for the next reader"

# Full options
python -m grader --help
```

## Architecture

The grader is a black-box sequencer. On every grading run the
grader probes the environment's HTTP endpoints
(`http://localhost/` for openeclass, `https://localhost:18443/health`
for the mock CAS), invokes `<mock-root>/scripts/reset` to flush the
seed back to its baseline, then sequences the phase modules:

1. Apply the patch on a fresh test branch (or skip in `--no-patch` baseline mode).
2. Python dependency install (`uv sync` against the participant's checkout) as a non-scored prerequisite. Failure skips every Python rubric row.
3. Python baseline phase (P.1.1 through P.1.10).
4. Python course-announcements phase (P.2.1 through P.2.8).
5. Python general-announcements phase (P.3.1 through P.3.6).
6. C compile (`make c-server`, scored as C.1.1).
7. C tech-stack verification (`ldd` whitelist, scored as C.1.2).
8. C baseline phase (C.2.1 through C.2.10).
9. C course-announcements phase (C.3.1 through C.3.8).
10. C general-announcements phase (C.4.1 through C.4.6).
11. C memory phase (four valgrind scenarios, C.5.1 through C.5.4).

Each protocol test spawns the participant's MCP server as a
subprocess (Python: `uv run python -m src.eclass_mcp_server.server`;
C: `c-replica/server` directly), sends JSON-RPC requests on stdin,
and asserts against the response's `text` content. Each memory
scenario wraps the C-replica spawn in `valgrind` and verifies a
clean exit with zero leaked bytes.

Phase failures are recorded in the results JSON without halting
the run. Patch-apply failures, pre-flight failures, and reset
failures terminate the run early.

## Pinned references

| Component | Pinned at |
|---|---|
| `eclass-mcp-server` | commit `dbd2d16` on the `main` branch |
| Testing environment (amd64) | `bsc-apm-case-study-task` release tag `bsc-apm-case-study-task` |
| Testing environment (arm64) | `bsc-apm-case-study-task` release tag `bsc-apm-case-study-task-arm64` |

A grading machine that produces a baseline score other than
9/100 against these pinned references is misconfigured.

## Seed-mirror sync

`grader/seed.yaml` is a pinned mirror of the testing environment's
seed file. The `Makefile` next to it carries two targets that keep
the mirror in lock-step with the upstream source:

```bash
# Diff the mirror against the testing environment's release tag.
# Exits 1 on drift.
make check-seed

# Overwrite the mirror's body from the testing environment's
# release tag, preserving the local header comment block.
make refresh-seed

# Override the pin via REF=<tag-or-sha>:
make check-seed REF=main
```

Default `REF` is `bsc-apm-case-study-task` (the amd64 release tag),
so reproducibility tracks the released testing-environment surface.
Run `make check-seed` before any grading run that uses a re-cut
testing-environment release; run `make refresh-seed` to bring the
mirror forward when drift surfaces.

## Directory structure

```
grader/
├── __init__.py
├── __main__.py                       # CLI entry: python -m grader
├── inspect.py                        # results browser
├── notes.py                          # CLI entry: python -m grader.notes
├── Makefile                          # seed-mirror sync targets
├── README.md
├── seed.yaml                         # pinned mirror of the testing env's seed
└── src/
    ├── __init__.py
    ├── config.py                     # path resolution from CLI flags or grader.yaml
    ├── errors.py                     # GraderError hierarchy
    ├── preflight.py                  # HTTP probes against the testing environment
    ├── reset.py                      # subprocess invocation of scripts/reset
    ├── patch.py                      # git apply / cleanup
    ├── build_python.py               # uv sync for the Python implementation
    ├── build_c.py                    # C.1.1 compile and C.1.2 stack verification
    ├── seed.py                       # seed.yaml loader and per-window helpers
    ├── scoring.py                    # rubric definitions and the Scorer
    ├── reporting.py                  # JSON, text, and console writers
    └── protocol/
        ├── __init__.py
        ├── runner.py                       # server spawn, JSON-RPC framing
        ├── _announcements_assertions.py    # shared count/body helpers
        ├── baseline_tests.py               # P.1 / C.2 assertions
        ├── course_announcements_tests.py   # P.2 / C.3 assertions
        ├── general_announcements_tests.py  # P.3 / C.4 assertions
        ├── memory_tests.py                 # C.5 scenarios under valgrind
        ├── python_baseline.py               # phase aggregator (impl=python)
        ├── python_course_announcements.py   # phase aggregator (impl=python)
        ├── python_general_announcements.py  # phase aggregator (impl=python)
        ├── c_baseline.py                    # phase aggregator (impl=c)
        ├── c_course_announcements.py        # phase aggregator (impl=c)
        ├── c_general_announcements.py       # phase aggregator (impl=c)
        └── c_memory.py                      # phase aggregator (impl=c)
```

## Related

- [bsc-apm-case-study-task](https://github.com/sdi2200262/bsc-apm-case-study-task):
  the participant testing environment and task specification the grader runs against.
- [../parser/](../parser/): transcript parser for participant
  Claude Code session logs.
- [../pipeline/](../pipeline/): submission processing pipeline
  that orchestrates validation, grading, parsing, and dataset
  aggregation.
- [Task specification](https://github.com/sdi2200262/bsc-apm-case-study-task/tree/main/participant/task):
  the PRD and prompt participants implement against.
- [SCORING.md](SCORING.md): rubric the grader implements against.
