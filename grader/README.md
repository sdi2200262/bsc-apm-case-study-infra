# Grader

Black-box testing suite for evaluating participant submissions
against the pinned `eclass-mcp-server` baseline. The grader applies
a participant's patch on a fresh test branch, runs the rubric
checks against a separately-installed grading environment, and
writes a JSON results artefact the pipeline promotes into the
dataset.

## Overview

The grader scores a participant's submission against a 100-point
rubric of 90 atomic rows: 30 points to the Python implementation and
70 to the C replica. [SCORING.md](SCORING.md) is the rubric itself:
every row and its points, the baseline-versus-feature split, and the
per-section budget the grader asserts at import.

The participant workspace is shipped separately by the
[`bsc-apm-case-study-task`](https://github.com/sdi2200262/bsc-apm-case-study-task)
repository; the grader probes its endpoints, invokes its reset script,
and spawns participant MCP servers under environment variables
derived from its install prefix.

## Prerequisites

**Operating system.** Linux (native, WSL2, or a Linux VM on macOS).

**Required software.**

- Python 3.12 or newer with `uv` on `PATH`.
- Docker Engine plus Compose v2 (consumed by the grading environment).
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

## Grading environment

The `bsc-apm-case-study-task` repository ships per-architecture release
tarballs (amd64 and arm64); install instructions, lifecycle scripts,
and seed documentation live in that repository's
[INSTALL.md](https://github.com/sdi2200262/bsc-apm-case-study-task/blob/main/docs/INSTALL.md).
The grader expects the grading environment to be installed and
running before it is invoked.

## Quick start

```bash
# Bring the grading environment up (one-time install plus scripts/up;
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

# Emit the rubric schema once (the static per-row metadata)
python -m grader --schema -o /path/to/output-dir

# Browse a results JSON in the terminal (joins the schema for the
# row descriptions, categories, and point maxima)
./inspect.py /path/to/grader_results.json --schema /path/to/grader_schema.json

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
seed back to its baseline, then runs each rubric group in turn:

1. Apply the patch on a fresh test branch (or skip in `--no-patch` baseline mode).
2. Provision the dev environment: copy `<mock-root>/.env` and `<mock-root>/certs/` verbatim into the checkout, overwriting any `.env` or cert shipped inside the patch. A preflight verifies both source artefacts are present. Provisioning is reset per submission.
3. Python dependency install (`uv sync` against the participant's checkout) as a non-scored prerequisite. Failure skips every Python rubric row.
4. Python baseline group (P.1.1 through P.1.11).
5. Python course-announcements group (P.2.1 through P.2.9).
6. Python general-announcements group (P.3.1 through P.3.7).
7. C compile (`make c-server`, scored as C.1.1). C.1.1 is the sole hard gate: on fail every other C row is skip-recorded and the run proceeds to reporting.
8. C stack verification (`ldd`): C.1.2 requires libcurl present, C.1.3 requires libxml2 present, C.1.4 requires no JSON-parsing library; transitive dependencies are otherwise unrestricted (no cascade from any of these).
9. C configuration-surface probes: C.1.5 env-var surface, C.1.6 verbatim documented `.env` surface (no cascade; restores dual-provisioned state after).
10. C baseline group (C.2.1 through C.2.12). C.2.3 through C.2.12 each also record a `.mem` sub-assertion scored only when the functional assertion passes.
11. C course-announcements group (C.3.1 through C.3.9), each with a `.mem` sub-assertion.
12. C general-announcements group (C.4.1 through C.4.7), each with a `.mem` sub-assertion.
13. C memory group: three multi-step valgrind scenarios (C.5.1 through C.5.3), each gated on the composed single-call scenarios named in its `gates_on` tuple.

Each protocol test spawns the participant's MCP server as a
subprocess (Python: `uv run python -m src.eclass_mcp_server.server`;
C: `c-replica/server` directly), sends JSON-RPC requests on stdin,
and asserts against the response's `text` content. C functional
scenarios run under valgrind; the `.mem` sub-assertion passes when
the functional scenario passes AND valgrind exits cleanly with zero
leaked bytes.

The seed and the `.env`/`certs/` provisioning are separate
mechanisms. The grader reads the grading environment's own
`grader-env/seed/seed.yaml` (the file the environment image is built
from) so the rubric's expected values cannot drift from the
environment under test; the `.env`/`certs/` copy guarantees the
participant server's wiring is the literal documented wiring.

Test failures are recorded in the results JSON without halting the
run. Patch-apply, provisioning, pre-flight, and reset failures
terminate the run early, each printing one actionable line on stderr.

The results JSON carries only each row's per-submission outcome (its
verdict, credited points, message, and captured output). The static
rubric metadata each row is read against, its point maximum, category,
target, and description, lives once in `grader_schema.json`, emitted by
`python -m grader --schema`; `inspect.py` joins it to render the
descriptive views. This mirrors the parser's `parser_schema.json` and
keeps the per-submission artifact free of metadata that repeats
identically across every grading.

The scored verdicts are reproducible against the pinned references
below, but the captured `full_output` transcript is not byte-stable
across seedings: the seed writes each announcement date relative to
the seeding wall clock, and the C.1.2 `ldd` capture includes
loader-assigned addresses, so two environments seeded on different
days score identically but produce divergent transcripts. Compare
results JSON on the verdicts, not by byte diff.

## Compact serialization mode

The grader emits outgoing JSON-RPC through `json.dumps` (a space after
each `,` and `:`); the reference Python server, on the MCP SDK stdio
transport, emits compact. Per
[RFC 8259 section 2](https://www.rfc-editor.org/rfc/rfc8259#section-2)
that whitespace is insignificant, and
[JSON-RPC 2.0](https://www.jsonrpc.org/specification) with the
[MCP stdio transport](https://modelcontextprotocol.io/specification/2025-03-26/basic/transports)
constrain structure and newline framing, not token spacing, so a
conformant parser accepts both forms.

`--compact-json` emits every frame compact and writes the result to
`grader_results_compact_serialization.json` beside the canonical `grader_results.json`,
recording how a sound-but-compact-only replica would score. Only
emission changes; the read side is whitespace-insensitive.

```bash
python -m grader /path/to/solution.patch \
    --eclass-dir /path/to/eclass-mcp-server \
    --mock-root ~/.bsc-apm \
    --compact-json
```

## Pinned references

| Component | Pinned at |
|---|---|
| `eclass-mcp-server` | commit `dbd2d16` on the `main` branch |
| Grading environment (amd64) | `bsc-apm-case-study-task` release tag |
| Grading environment (arm64) | `bsc-apm-case-study-task-arm64` release tag |

## Directory structure

```
grader/
├── __init__.py
├── __main__.py                        # CLI entry: python -m grader
├── inspect.py                         # one-shot results browser; joins grader_schema.json
├── notes.py                           # CLI entry: python -m grader.notes
├── log.py                             # terminal-output routing (all human output)
├── config.py                          # path resolution from CLI flags or grader.yaml
├── errors.py                          # GraderError hierarchy
├── README.md
├── SCORING.md
├── environment/                       # sandbox-preparation layer
│   ├── __init__.py
│   ├── preflight.py                   # HTTP probes against the grading environment
│   ├── reset.py                       # subprocess invocation of scripts/reset
│   ├── patch.py                       # git apply / cleanup
│   ├── provision.py                   # verbatim .env + certs/ provisioning from mock-root
│   ├── env_file.py                    # single-source .env parser (provision + runner)
│   ├── build_python.py                # uv sync for the Python implementation
│   └── build_c.py                     # C.1.1 compile and C.1.2 to C.1.4 stack verification
├── protocol/                          # MCP engine, oracle, and the rubric-group suites
│   ├── __init__.py
│   ├── runner.py                      # server spawn, JSON-RPC framing, fixtures
│   ├── _jsonrpc_io.py                 # JSON-RPC stdio reads + shared outgoing-frame serializer
│   ├── _schema_validation.py          # tools/call argument validation against inputSchema
│   ├── _memcheck.py                   # valgrind stderr parsing helpers
│   ├── server_env.py                  # spawned-server environment block (from <mock-root>/.env)
│   ├── calibration.py                 # per-run seed-apply instant from MariaDB
│   ├── seed.py                        # grader-env seed loader and per-principal/window helpers
│   ├── expected.py                    # expected response strings and the constructed handshake contract
│   ├── matching.py                    # acceptance policy (byte-exact, whitespace-normalised, two-form)
│   ├── announcement_matching.py       # announcement parsing and date canonicalisation
│   └── groups/                        # rubric-group runners and the per-group assertion suites
│       ├── __init__.py                # re-exports the eight run_* entry points
│       ├── runners.py                 # per-(implementation, group) aggregation entries
│       ├── _support.py                # shared scenario scaffolding + .mem-recording helper
│       ├── baseline.py                # P.1 / C.2 assertions
│       ├── frame.py                   # tools/list and C initialize-frame assertions
│       ├── course_announcements.py    # P.2 / C.3 assertions
│       ├── general_announcements.py   # P.3 / C.4 assertions
│       ├── memory.py                  # C.5 multi-step scenarios under valgrind
│       └── config_surface.py          # C.1.5 / C.1.6 surface-isolated probes
├── scoring/                          # scoring layer: rubric authority + aggregation
│   ├── __init__.py
│   ├── rubric.py                      # the 90 test definitions, groupings, and schema_document
│   └── scoring.py                     # the Scorer and the point-budget guard
└── report/                           # report layer: artefact, console, notices
    ├── __init__.py
    ├── build.py                       # JSON results artefact writer
    ├── render.py                      # console grading summary
    └── notices.py                     # REVIEW/WARNING notice policy
```

## Related

- [bsc-apm-case-study-task](https://github.com/sdi2200262/bsc-apm-case-study-task):
  the participant workspace and task specification the grader runs against.
- [../parser/](../parser/): transcript parser for participant
  Claude Code session logs.
- [../pipeline/](../pipeline/): submission processing pipeline
  that orchestrates validation, grading, parsing, and dataset
  aggregation.
- [Task specification](https://github.com/sdi2200262/bsc-apm-case-study-task/tree/main/participant/task):
  the PRD and prompt participants implement against.
- [SCORING.md](SCORING.md): rubric the grader implements against.
