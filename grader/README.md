# Grader

Black-box testing suite for evaluating participant submissions
against the pinned `eclass-mcp-server` baseline. The grader applies
a participant's patch on a fresh test branch, runs the rubric
phases against a separately-installed testing environment, and
writes a JSON results artefact the pipeline promotes into the
dataset.

## Overview

The grader scores a participant's submission against a 100-point
rubric covering 90 atomic rows: 30 points to the Python
implementation and 70 points to the C replica. The Python
implementation contributes 11 baseline rows worth 11 points and 16
feature rows worth 19 points (9 course-announcement rows worth 11
points plus 7 general-announcement rows worth 8 points, with three
of those feature rows worth 2 points each). The C replica
contributes 37 functional and infrastructure rows (6 infra, 12
baseline, 9 course, 7 general, 3 multi-step memory) plus 26
per-scenario memory sub-assertions, each sub-assertion awarded only
when its paired functional scenario passes.

The participant testing environment is shipped separately by the
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
- `pkg-config` (used to probe the libcurl and libxml2 versions).
- `valgrind`.
- `make`.

Ubuntu install lines:

```bash
sudo apt-get install -y python3 git build-essential pkg-config \
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
2. Provision the dev environment: copy `<mock-root>/.env` and `<mock-root>/certs/` verbatim into the checkout, overwriting any `.env` or cert shipped inside the patch. A preflight verifies both source artefacts are present. Provisioning is reset per submission.
3. Python dependency install (`uv sync` against the participant's checkout) as a non-scored prerequisite. Failure skips every Python rubric row.
4. Python baseline phase (P.1.1 through P.1.11).
5. Python course-announcements phase (P.2.1 through P.2.9).
6. Python general-announcements phase (P.3.1 through P.3.7).
7. C compile (`make c-server`, scored as C.1.1). C.1.1 is the sole hard gate: on fail every other C row is skip-recorded and the run proceeds to reporting.
8. C tech-stack verification (`ldd` whitelist): C.1.2 libcurl, C.1.3 libxml2, C.1.4 no-JSON-library (no cascade from any of these).
9. C configuration-surface probes: C.1.5 env-var surface, C.1.6 verbatim documented `.env` surface (no cascade; restores dual-provisioned state after).
10. C baseline phase (C.2.1 through C.2.12). C.2.3 through C.2.12 each also record a `.mem` sub-assertion scored only when the functional assertion passes.
11. C course-announcements phase (C.3.1 through C.3.9), each with a `.mem` sub-assertion.
12. C general-announcements phase (C.4.1 through C.4.7), each with a `.mem` sub-assertion.
13. C memory phase: three multi-step valgrind scenarios (C.5.1 through C.5.3), each gated on the composed single-call scenarios named in its `gates_on` tuple.

Each protocol test spawns the participant's MCP server as a
subprocess (Python: `uv run python -m src.eclass_mcp_server.server`;
C: `c-replica/server` directly), sends JSON-RPC requests on stdin,
and asserts against the response's `text` content. C functional
scenarios run under valgrind; the `.mem` sub-assertion passes when
the functional scenario passes AND valgrind exits cleanly with zero
leaked bytes.

The seed and the `.env`/`certs/` provisioning are separate
mechanisms: the grader reads the grading environment's own
`grader-env/seed/seed.yaml` (the same file the environment image is
built from, in this repository) so the rubric's expected data
values cannot drift from the environment under test; the
`.env`/`certs/` copy guards that the participant server's wiring to
the testing environment is the literal documented wiring.

Phase failures are recorded in the results JSON without halting
the run. Patch-apply failures, provisioning failures, pre-flight
failures, and reset failures terminate the run early; every such
failure prints one actionable line on stderr.

The scored verdicts in the results JSON are reproducible against
the pinned references below; the captured `full_output` transcript
text is not byte-stable across seedings. The testing environment's
seed writes each announcement date at insert time as the seeding
wall clock minus the entry's `days_ago`, and the C.1.2 `ldd`
capture includes loader-assigned load addresses, so two grading
environments seeded on different days yield identical scores but
textually divergent transcripts. Compare results JSON on the
verdicts, not by byte diff.

## Pinned references

| Component | Pinned at |
|---|---|
| `eclass-mcp-server` | commit `dbd2d16` on the `main` branch |
| Testing environment (amd64) | `bsc-apm-case-study-task` release tag `bsc-apm-case-study-task` |
| Testing environment (arm64) | `bsc-apm-case-study-task` release tag `bsc-apm-case-study-task-arm64` |

## Directory structure

```
grader/
├── __init__.py
├── __main__.py                       # CLI entry: python -m grader
├── inspect.py                        # results browser
├── notes.py                          # CLI entry: python -m grader.notes
├── README.md
└── src/
    ├── __init__.py
    ├── config.py                     # path resolution from CLI flags or grader.yaml
    ├── errors.py                     # GraderError hierarchy
    ├── preflight.py                  # HTTP probes against the testing environment
    ├── reset.py                      # subprocess invocation of scripts/reset
    ├── patch.py                      # git apply / cleanup
    ├── env_file.py                   # single-source .env parser (provision + runner)
    ├── provision.py                  # verbatim .env + certs/ provisioning from mock-root
    ├── build_python.py               # uv sync for the Python implementation
    ├── build_c.py                    # C.1.1 compile and C.1.2/C.1.3/C.1.4 stack verification
    ├── seed.py                       # grader-env seed loader and per-principal/window helpers
    ├── scoring.py                    # rubric definitions and the Scorer
    ├── reporting.py                  # JSON, text, and console writers
    └── protocol/
        ├── __init__.py
        ├── runner.py                       # server spawn, JSON-RPC framing, schema-gated tools/call
        ├── server_env.py                   # spawned-server environment block (single-sourced from <mock-root>/.env)
        ├── _memcheck.py                    # valgrind stderr parsing helpers
        ├── _assertion_support.py           # shared scenario scaffolding + .mem-recording helper
        ├── calibration.py                  # per-run seed-apply instant from MariaDB
        ├── expected.py                     # expected response strings and the constructed handshake contract
        ├── matching.py                     # acceptance policy (byte-exact, whitespace-normalised, two-form)
        ├── baseline_tests.py               # P.1 / C.2 assertions
        ├── course_announcements_tests.py   # P.2 / C.3 assertions
        ├── general_announcements_tests.py  # P.3 / C.4 assertions
        ├── config_surface.py               # C.1.5 / C.1.6 surface-isolated probes
        ├── memory_tests.py                 # C.5 multi-step scenarios under valgrind
        ├── python_baseline.py               # phase aggregator (impl=python)
        ├── python_course_announcements.py   # phase aggregator (impl=python)
        ├── python_general_announcements.py  # phase aggregator (impl=python)
        ├── c_baseline.py                    # phase aggregator (impl=c)
        ├── c_config.py                      # phase aggregator (impl=c, C.1.5/C.1.6)
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
