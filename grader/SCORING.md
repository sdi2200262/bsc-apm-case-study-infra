# Scoring Rubric

Total: 100 points across 90 atomic rows. The Python implementation
holds 30 points across 27 rows; the C replica holds 70 across 63
rows, of which 37 are functional or infrastructure rows and 26 are
per-scenario memory sub-assertions. [scoring/rubric.py](scoring/rubric.py)
declares every row and [scoring/scoring.py](scoring/scoring.py) asserts
this per-section budget at import; a
numeric drift between this document and the code is a bug in this
document.

The grader is a JSON-RPC black box: it observes only the `text`
content of each tool response and the dynamic-link stack of the C
binary, never the participant's source. Every row tests a behaviour
[PRD §2] specifies for the two announcement tools, or an
inherited-tool contract the PRD requires the deliverables to
reproduce and delegates to the `eclass-mcp-server` reference docs, per
[PRD §1] and [PRD §3]. [PRD §5] checks its acceptance criteria
verbatim, failing validation on any deviation in punctuation,
wording, or whitespace, so byte-exact matching is the default. The
grader relaxes it only where the PRD leaves a rendering open or the
referenced material disagrees with the upstream source it describes,
and flags every relaxed acceptance for human review.

## Assertion model

Every announcement and `get_courses` response, every error string,
and every empty-window response is matched against a full constructed
string; there are no substring matches. Fixed-string rows (errors
and empty-window responses) match under one of two strictness modes,
recorded as the row's diagnostic
([protocol/matching.py](protocol/matching.py)):

- `byte-exact`: the response equals the constructed string byte for
  byte.
- `whitespace-normalized`: the two match after the non-breaking space
  family (U+00A0, U+2007, U+2009, U+202F) is mapped to an ASCII space
  on both sides. The platform's locale renderer emits U+202F before
  the meridiem in dates and the PRD treats normalised whitespace as
  equivalent, so this mode records that the acceptance relied on that
  rule.

The announcement success rows are not fixed strings. [PRD §2] fixes
the announcement content and the recency filter, [PRD §4] leaves the
date *rendering* locale-specific, and the PRD pins no presentation
order, so the matcher in
[protocol/announcement_matching.py](protocol/announcement_matching.py)
canonicalises each `Date:` line to a calendar date, normalises the
surrounding text, and accepts either form:

- `announcements-ordered`: the openeclass-derived entries in
  date-descending order.
- `announcements-unordered`: the same entry multiset and count, with
  sequence and per-entry index not enforced. This is a lenient form;
  see Review and warning flags.

Three further rows accept two forms because the material the PRD
points at disagrees with the upstream source it describes; the grader
takes either the doc-faithful or the source-faithful reading.
[protocol/expected.py](protocol/expected.py) constructs both forms
per row and [protocol/matching.py](protocol/matching.py) records
which matched:

- `get_courses`. `get-courses-faithful` is the openeclass layout glue
  and `(code)` suffix the reference server reproduces;
  `get-courses-documented` is the clean bare title
  `tools-reference.md` documents.
- Missing credentials, C.2.7. `missing-creds-faithful` is the Python
  reference's two-sentence error; `missing-creds-documented` is the
  one-sentence form the reference doc documents.
- `initialize` capabilities, C.2.1. `capabilities-faithful` is the
  object the MCP SDK serialises for a tools-only server;
  `capabilities-documented` is the object
  `eclass-mcp-server/docs/reference/wire-protocol.md` documents.

The `tools/list` row, checked at P.1.1 and C.2.2, advertises exactly
the six tools, order-insensitive, with none missing or extra and
every entry a JSON object carrying a string `name`. Each tool's
`name` and `inputSchema` are byte-exact: the four baseline tools
against the wire-protocol reference, the two announcement tools
against the schemas [PRD §2] prints verbatim. The `description` field
is byte-exact for the four baseline tools, whose wording is the
inherited reference contract; the PRD specifies no tool-level
description for the two announcement tools, so theirs is accepted as
any non-empty string and recorded as `description-presence-only`, a
lenient form.

The `initialize` frame at C.2.1 matches `protocolVersion` and
`serverInfo` byte-exact before the two-form capabilities check above.

## Partial credit

A string-matched row the matcher rejects is scored for nearness to its
expected output, so a row's `verdict` is `passed` (an accepted form
matched, full `points`), `partial` (none matched but the response is
near one, earning `points` times its similarity and flagged for
review), or `failed` (zero). Nearness is a Levenshtein edit-distance
ratio in `[0, 1]` on the whitespace-normalized forms, against the
closest accepted form ([protocol/similarity.py](protocol/similarity.py);
see [Levenshtein distance]). A row scores `partial` at or above a floor,
default `0.45` ([config.py](config.py)), overridable under
`partial.floor` in `grader.yaml` or with `--partial-floor` (CLI over
`grader.yaml` over the default).

Partial credit never moves a strict grade: only a row that matched no
accepted form is eligible, and the structural and leak-only rows (the
`initialize` frame, `tools/list`, the memory rows) carry no similarity.
The similarity ratio is recorded in `results.json` on every string row
that ran the partial check, `partial` or `failed`, and is scored only on
`partial` rows, so the full ratio distribution is available for floor tuning.
Each score node reports `total_strict` (full points over `passed` rows),
`total_partial` (fractional credit from `partial` rows), `total` (their
sum), and `max`.

## Review and warning flags

[scoring/notices.py](scoring/notices.py) prints human-review flags
after the scores, in two categories:

- `REVIEW`: a row passed via a lenient form, or earned partial credit.
  The five lenient forms are `announcements-unordered`,
  `get-courses-documented`, `missing-creds-documented`,
  `capabilities-documented`, and `description-presence-only`; a
  `partial` row is a near-miss credited fractionally. The acceptance or
  the fractional award is qualitatively ambiguous, so a reviewer
  inspects the response and records any manual adjustment in
  `results_notes.yaml`.
- `WARNING`: a handshake row failed, one of P.1.1, C.2.1, or C.2.2.
  These compare against SDK-emitted serialisation, so a failure may
  be a participant defect, an SDK change since the expected values
  were captured, or grader over-specification; check for uniform
  cohort failure before judging.

The Python reference accepts only the strict forms; the C replica
accepts either form in each pair, because both are legitimate
readings of the published task material.

## Boundary semantics

`days_back=N` is an inclusive calendar-day filter: an announcement
`K` days old is in the window iff `K <= N`, per [PRD §2] and
[PRD §4]. [PRD §2] puts no upper bound on the per-course tool, so
`days_back=40` widens past the default 30. The general tool requires
`days_back` in `[0, 30]` and returns `Error: Cannot retrieve
announcements older than 30 days.` above 30, per [PRD §2] and
[PRD §5]; the 30-day bound matches the openeclass portfolio query's
calendar-month floor on the seeded data.

## Memory checks

The C functional scenarios C.2 through C.4 run under
`valgrind --leak-check=full --show-leak-kinds=all
--track-origins=yes --error-exitcode=99`, driven by the same JSON-RPC
client as the Python rows. Each records a functional verdict under
`<id>` and a memory sub-assertion under `<id>.mem`, the latter scored
only when the functional row passes AND the run is leak-clean: it
completed with the leak summary present, was not signal-killed, did
not exit with the sentinel 99, and reported zero `definitely lost`
and zero `indirectly lost` bytes.
[protocol/_memcheck.py](protocol/_memcheck.py) enforces that verdict,
matching [PRD §5]. The 26 `.mem` sub-assertions cover C.2.3 through
C.2.12, C.3.1 through C.3.9, and C.4.1 through C.4.7; C.2.1, C.2.2,
and the C.1 infrastructure rows carry none.

The C.5 multi-step memory rows drive the binary once under the same
valgrind invocation with a scripted JSON-RPC sequence per scenario.
[protocol/groups/memory.py](protocol/groups/memory.py) gates each on
the functional rows whose call shapes it exercises, listed in its
`gates_on` tuple, and records a zero-point skip when any of those rows
did not pass, rather than driving valgrind through the participant's
error handling.

## Python Implementation (30 points across 27 rows)

The Python implementation extends the upstream `eclass-mcp-server`
reference with the two announcement tools the PRD adds. The baseline
rows run the four inherited tools against the seeded
`student_courses` principal; the feature rows run the two new tools
against the principal's enrolled courses.

### Baseline (11 points across 11 rows)

| ID | Points | Description |
|----|--------|-------------|
| P.1.1 | 1 | `tools/list` exposes all six tools with exact name and schema, descriptions byte-exact for the four baseline tools and presence-checked for the two announcement tools |
| P.1.2 | 1 | `authstatus` before login reports not-logged-in |
| P.1.3 | 1 | login with valid credentials succeeds |
| P.1.4 | 1 | `authstatus` on the live session reports the logged-in user |
| P.1.5 | 1 | second login while authenticated reports already-logged-in |
| P.1.6 | 1 | login with every credential surface deprived reports missing-credentials |
| P.1.7 | 1 | `get_courses` while logged in returns the faithful course list |
| P.1.8 | 1 | logout while authenticated succeeds |
| P.1.9 | 1 | `authstatus` after logout reports not-logged-in |
| P.1.10 | 1 | `get_courses` without authentication reports not-logged-in |
| P.1.11 | 1 | logout without a prior login is a no-op |

### Feature: Course Announcements (11 points across 9 rows)

`get_course_announcements` fetches a single course's announcements
and applies the `days_back` filter client-side; with no backend date
floor, every seeded announcement is visible and all filtering is the
participant's responsibility.

| ID | Points | Description |
|----|--------|-------------|
| P.2.1 | 1 | course tool without login returns the not-logged-in error |
| P.2.2 | 1 | unparseable `course_url` returns the extract-code error |
| P.2.3 | 1 | negative `days_back` returns the non-negative-integer error |
| P.2.4 | 1 | out-of-window course returns the empty-window string |
| P.2.5 | 2 | `days_back=0` returns the single relative-date announcement |
| P.2.6 | 1 | `days_back=0` on an absolute-only course returns the empty-window string |
| P.2.7 | 2 | default window returns the three in-scope announcements newest first |
| P.2.8 | 1 | `days_back=10` slices the explicit non-default window |
| P.2.9 | 1 | `days_back=40` widens past the default with no upper cap |

### Feature: General Announcements (8 points across 7 rows)

`get_general_announcements` unions the system-wide announcements with
those of every course the authenticated principal is enrolled in,
ordered newest first across both sources, and rejects `days_back`
above 30. The general suite runs against the `student_general`
principal, whose enrolment is disjoint from the baseline and course
suites, so the union covers both sources at the probed windows.

| ID | Points | Description |
|----|--------|-------------|
| P.3.1 | 1 | general tool without login returns the not-logged-in error |
| P.3.2 | 1 | negative `days_back` returns the non-negative-integer error |
| P.3.3 | 1 | `days_back=31` returns the older-than-30-days error |
| P.3.4 | 1 | `days_back=0` returns the empty-window string |
| P.3.5 | 1 | `days_back=5` returns the lone in-scope course entry with its source |
| P.3.6 | 2 | `days_back=8` returns the system and course union with both source forms |
| P.3.7 | 1 | default window returns the full union ordered across sources |

## C Replica (70 points across 63 rows)

The C replica is a separate program under
`<eclass-mcp-server>/c-replica/`, built by a participant-supplied
Makefile and invoked as a subprocess. [PRD §3] constrains its
technical stack: `libcurl` and `libxml2` are required, no
JSON-parsing library is permitted, so the participant parses JSON-RPC
manually, and transitive system dependencies are unrestricted.

### Build, technical stack, and configuration surfaces (6 points across 6 rows)

C.1.1 is the sole hard gate: on fail, every other C row is
skip-recorded, the `.mem` sub-assertions and the C.5 rows included.
C.1.2 through C.1.6 run independently with no cascade. [PRD §3] has
one `.env` at the package root serve both implementations and adds no
C-only configuration surface, so the grader scores each of the two
ways those values can reach the server on its own deprivation, in
[protocol/groups/config_surface.py](protocol/groups/config_surface.py): C.1.5
removes the on-disk `.env` and supplies the `ECLASS_*` values only as
process environment variables; C.1.6 removes the environment
variables and supplies them only as the verbatim `<mock-root>/.env`
copied into the package root. Each drives one authenticated `login`,
so a participant implementing only one surface is penalised once at
the probing row, not across the behavioural suites.

| ID | Points | Description |
|----|--------|-------------|
| C.1.1 | 1 | `make c-server` exits 0 and produces the server binary |
| C.1.2 | 1 | dynamic dependencies include libcurl |
| C.1.3 | 1 | dynamic dependencies include libxml2 |
| C.1.4 | 1 | dynamic dependencies exclude any JSON-parsing library |
| C.1.5 | 1 | serves a tool configured by environment variables only |
| C.1.6 | 1 | serves a tool configured by the package-root `.env` only |

[environment/build_c.py](environment/build_c.py) rejects any
dynamically-linked name matching
`^lib(json|cjson|jansson|yajl|jq|parson)` as a forbidden JSON parser.
The behavioural suites C.2 through C.5 run with both configuration
surfaces provisioned, so a participant implementing only one is still
measured on every behaviour.

### Baseline (13 points across 12 rows)

The C replica implements the four baseline tools from scratch plus
the two announcement tools, with no upstream C reference to inherit;
each row mirrors a P.1 behaviour against the C binary. C.2.1, the
constructed initialize frame, is worth 2 points because it asserts
the whole handshake contract.

| ID | Points | Description |
|----|--------|-------------|
| C.2.1 | 2 | the hand-written initialize frame (protocolVersion, capabilities, serverInfo) |
| C.2.2 | 1 | `tools/list` exposes all six tools with exact name and schema, descriptions byte-exact for the four baseline tools and presence-checked for the two announcement tools |
| C.2.3 | 1 | `authstatus` before login reports not-logged-in |
| C.2.4 | 1 | login with valid credentials succeeds |
| C.2.5 | 1 | `authstatus` on the live session reports the logged-in user |
| C.2.6 | 1 | second login while authenticated reports already-logged-in |
| C.2.7 | 1 | login with every credential surface deprived reports missing-credentials |
| C.2.8 | 1 | `get_courses` while logged in returns an accepted course-list form |
| C.2.9 | 1 | logout while authenticated succeeds |
| C.2.10 | 1 | `authstatus` after logout reports not-logged-in |
| C.2.11 | 1 | `get_courses` without authentication reports not-logged-in |
| C.2.12 | 1 | logout without a prior login is a no-op |

### Feature: Course Announcements (11 points across 9 rows)

| ID | Points | Description |
|----|--------|-------------|
| C.3.1 | 1 | course tool without login returns the not-logged-in error |
| C.3.2 | 1 | unparseable `course_url` returns the extract-code error |
| C.3.3 | 1 | negative `days_back` returns the non-negative-integer error |
| C.3.4 | 1 | out-of-window course returns the empty-window string |
| C.3.5 | 2 | `days_back=0` returns the single relative-date announcement |
| C.3.6 | 1 | `days_back=0` on an absolute-only course returns the empty-window string |
| C.3.7 | 2 | default window returns the three in-scope announcements newest first |
| C.3.8 | 1 | `days_back=10` slices the explicit non-default window |
| C.3.9 | 1 | `days_back=40` widens past the default with no upper cap |

### Feature: General Announcements (8 points across 7 rows)

| ID | Points | Description |
|----|--------|-------------|
| C.4.1 | 1 | general tool without login returns the not-logged-in error |
| C.4.2 | 1 | negative `days_back` returns the non-negative-integer error |
| C.4.3 | 1 | `days_back=31` returns the older-than-30-days error |
| C.4.4 | 1 | `days_back=0` returns the empty-window string |
| C.4.5 | 1 | `days_back=5` returns the lone in-scope course entry with its source |
| C.4.6 | 2 | `days_back=8` returns the system and course union with both source forms |
| C.4.7 | 1 | default window returns the full union ordered across sources |

### Multi-step memory (6 points across 3 scenarios)

The multi-step scenarios are scored as described under Memory checks:
the binary is driven once under valgrind with a scripted JSON-RPC
sequence, and a scenario passes only on a clean leak verdict, namely
zero `definitely lost` and zero `indirectly lost` bytes, run
complete, no signal exit, and exit code not the sentinel 99. Each
gates on the functional rows it exercises and is a zero-point skip
when any has not passed.

| ID | Points | Description |
|----|--------|-------------|
| C.5.1 | 2 | session-spanning allocation and free across the full tool surface |
| C.5.2 | 2 | session-state replacement on re-login and idempotent teardown |
| C.5.3 | 2 | leak and responsiveness on the pure baseline regression surface |

### Per-scenario memory sub-assertions (26 points across 26 rows)

Every C functional row from C.2.3 through C.4.7 also records a
one-point `<id>.mem` sub-assertion from the same valgrind run that
produced its functional verdict, awarded only when the functional row
passed AND the leak verdict was clean, as defined under Memory checks.
A failed functional row earns no `.mem` credit; a leak under a passing
row deducts the `.mem` point without affecting the functional verdict.
The pairing is mechanical, and the single per-row point weights
correctness against leak hygiene evenly on the same execution.

## Expected score upper bounds

| Submission shape | Score |
|---|---|
| No patch (baseline run against the unmodified upstream) | TBC |
| Python implementation only (no C replica produced) | 30/100 (C.1.1 fails its sole hard gate; every other C row skip-records) |
| Complete correct implementation | 100/100 |

[PRD §1]: https://github.com/sdi2200262/bsc-apm-case-study-task/blob/main/participant/task/PRD.md#1-overview
[PRD §2]: https://github.com/sdi2200262/bsc-apm-case-study-task/blob/main/participant/task/PRD.md#2-announcement-tools-implementation
[PRD §3]: https://github.com/sdi2200262/bsc-apm-case-study-task/blob/main/participant/task/PRD.md#3-native-c-replica-implementation
[PRD §4]: https://github.com/sdi2200262/bsc-apm-case-study-task/blob/main/participant/task/PRD.md#4-cross-cutting-requirements
[PRD §5]: https://github.com/sdi2200262/bsc-apm-case-study-task/blob/main/participant/task/PRD.md#5-acceptance-criteria
[Levenshtein distance]: https://en.wikipedia.org/wiki/Levenshtein_distance
