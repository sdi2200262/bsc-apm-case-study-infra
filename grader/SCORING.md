# Scoring Rubric

Total: 100 points across 90 atomic rows. The Python implementation
contributes 30 points across 27 rows; the C replica contributes 70
points across 63 rows (37 functional/infrastructure rows plus 26
per-scenario memory sub-assertions). The grader (`grader/src/scoring.py`)
declares every row and asserts the tier budget at import; a numeric
drift between this document and the code is a bug in this document.

The grader is a JSON-RPC black box: it observes only the `text`
content of each tool response and the dynamic-link stack of the C
binary. It does not read the participant's source.

## Assertion model

Every announcement and `get_courses` response, every error string,
and every empty-window response is asserted against a full
constructed string. There are no substring matches.

Two strictness modes apply to the fixed-string rows (errors and
empty-window responses):

- `byte-exact`: the response equals the constructed expected string
  byte for byte.
- `whitespace-normalized`: the response equals the constructed
  expected string after the non-breaking space family (U+00A0,
  U+2007, U+2009, U+202F) is mapped to an ASCII space on both sides.
  The participant testing environment renders dates with U+202F
  before the meridiem under recent CLDR; the PRD's whitespace rule
  treats normalised whitespace as equivalent, so this mode records
  that the acceptance relied on that rule.

Two acceptance forms apply to the announcement success rows and to
`get_courses`, because the PRD specifies the response format and
content but not a presentation order or a single layout:

- Announcements (per-course and general):
  - Form 1 `announcements-ordered`: the response equals the
    openeclass-derived ordered string (per-course rows ordered
    date-descending; general rows ordered across the system-wide and
    enrolled-course union, newest first) under
    `whitespace-normalized`.
  - Form 2 `announcements-unordered`: the response parses by the
    PRD's announcement grammar into the same multiset of byte-exact
    entries (after whitespace normalisation) with the same count, but
    the sequence and the per-entry index number are not enforced.
- `get_courses`:
  - Form 1 `get-courses-faithful`: the openeclass-formatted layout
    (a course title followed by the openeclass-version-specific
    layout glue and the `(code)` suffix).
  - Form 2 `get-courses-documented`: the documented-clean layout per
    `tools-reference.md` (the bare course title).
- Missing-credentials error (C.2.7):
  - Form 1 `missing-creds-faithful`: the two-sentence error the
    Python reference emits verbatim (`Error:` prefix, the `.env`
    requirement sentence followed by the `ECLASS_USERNAME` /
    `ECLASS_PASSWORD` instruction sentence).
  - Form 2 `missing-creds-documented`: the one-sentence form the
    reference doc documents (`Error:` prefix and the single
    `Username and password must be provided in the .env file`
    message, no second sentence). Accepted for the C replica only.

The `initialize` row (C.2.1) follows the same two-form pattern, with
byte-exact `protocolVersion` and `serverInfo` plus one of two
accepted `capabilities` objects:

- Form 1 `capabilities-faithful`: the object the MCP SDK serialises
  for a low-level tools-only server.
- Form 2 `capabilities-documented`: the object the project's
  wire-protocol reference (`eclass-mcp-server/docs/reference/
  wire-protocol.md`) literally documents.

The two differ; both are accepted because a participant who uses
the SDK ends up at the faithful shape and a participant who reads
the wire-protocol reference and transcribes it ends up at the
documented shape.

The accepted form is recorded as the row's diagnostic. The lenient
second form in each pair (`announcements-unordered`,
`get-courses-documented`, `capabilities-documented`,
`missing-creds-documented`) prints a WARNINGS line to stdout at the
end of grading that names the row and shows its response, prompting
the operator to review the row and decide any manual deduction
recorded in `results_notes.yaml`. The Python reference accepts only
the openeclass-derived forms for the announcement and `get_courses`
rows and the two-sentence form for the missing-credentials row; the
C replica accepts either, because both are legitimate readings of
the published task materials.

The `tools/list` row (P.1.1 / C.2.2) is one byte-exact contract for
both implementations: every tool object's `name`, `description`, and
`inputSchema` must equal the constructed expected values byte for
byte, order-insensitive, with no extra tools, and every advertised
entry itself must be a JSON object with a string `name`. Per-tool
divergence (an extra schema keyword, a regenerated description, a
different serialised shape, a non-object entry) fails this row.

The handshake rows (P.1.1, C.2.1, C.2.2) compare against
SDK-emitted serialisation. A failure here may reflect a participant
defect OR an SDK behavioural change since the expected values were
captured; the WARNINGS block surfaces handshake-row failures
alongside the lenient acceptances so the reviewer can inspect the
detail before judging.

## Boundary semantics

`days_back=N` is an inclusive filter on the announcement's age in
whole days. An announcement at `days_ago=K` is in scope iff
`K <= N`. The per-course endpoint applies no backend date floor; the
general endpoint clamps `days_back` to 30, matching the openeclass
portfolio query's calendar-month floor on the seeded data.

The C functional scenarios (C.2 through C.4) run under
`valgrind --leak-check=full --show-leak-kinds=all
--track-origins=yes --error-exitcode=99` driven by the same JSON-RPC
client as the Python rows. Each row records a functional verdict
under `<id>` and a memory sub-assertion under `<id>.mem` scored only
when the functional row passes AND valgrind ran to completion with
zero `definitely lost` bytes and zero `indirectly lost` bytes. The
`.mem` sub-assertions cover C.2.3 through C.2.12, C.3.1 through
C.3.9, and C.4.1 through C.4.7 (26 rows in total). C.2.1, C.2.2, and
the C.1 infrastructure rows carry no `.mem` sub-assertion.

The C multi-step memory rows (C.5) drive the C binary once under
valgrind with a scripted JSON-RPC sequence per scenario; each scenario
names the functional rows whose call shapes it exercises and is
skipped when any of those rows did not pass.

## Python Implementation (30 points across 27 rows)

The Python implementation extends the upstream `eclass-mcp-server`
reference with the two announcement tools the task PRD specifies.
The baseline tier runs the four inherited tools against the seeded
`student_courses` principal; the feature tiers run the two new tools
against the principal's enrolled courses.

### Baseline (11 points across 11 rows)

| ID | Points | Description |
|----|--------|-------------|
| P.1.1 | 1 | `tools/list` exposes all six tools with exact name, description, and schema |
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
and applies a client-side `days_back` filter. The per-course endpoint
applies no backend date floor, so every seeded announcement is
visible and all filtering is the participant's responsibility.

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

`get_general_announcements` unions the system-wide announcements
with the announcements of every course the authenticated principal
is enrolled in and orders the result newest first across both
sources. The endpoint clamps `days_back` to 30. The general suite
runs against the `student_general` principal (enrolled disjoint from
the baseline and course suites) so the union covers both sources at
the documented window probes.

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
`<eclass-mcp-server>/c-replica/`. It is built by a participant-supplied
Makefile and invoked by the grader as a subprocess. The technical
stack constraint: `libcurl` and `libxml2` are required; no
JSON-parsing library is permitted; the participant parses JSON-RPC
manually. Transitive system dependencies of `libcurl` and `libxml2`
are unrestricted.

### Build, technical stack, and configuration surfaces (6 points across 6 rows)

C.1.1 is the sole hard gate: on fail, every other C row (including
all `.mem` sub-assertions and the C.5 multi-step memory rows) is
skip-recorded. C.1.2 through C.1.6 run independently with no
cascade. The two configuration surfaces (C.1.5, C.1.6) are scored
each on its own deliberate deprivation: C.1.5 deprives the on-disk
`.env` and supplies the `ECLASS_*` values only as process
environment variables; C.1.6 deprives the environment variables and
supplies the values only as the verbatim `<mock-root>/.env` copied
into the package root. Each probe drives one authenticated `login`
to exercise the surface; a participant that implements only one
surface is penalised once at the row that probes the missing
surface, not in the behavioural suites.

| ID | Points | Description |
|----|--------|-------------|
| C.1.1 | 1 | `make c-server` exits 0 and produces the server binary |
| C.1.2 | 1 | dynamic dependencies include libcurl |
| C.1.3 | 1 | dynamic dependencies include libxml2 |
| C.1.4 | 1 | dynamic dependencies exclude any JSON-parsing library |
| C.1.5 | 1 | serves a tool configured by environment variables only |
| C.1.6 | 1 | serves a tool configured by the package-root `.env` only |

The forbidden JSON-parser library names match the regex
`^lib(json|cjson|jansson|yajl|jq|parson)`. The behavioural suites
(C.2 through C.5) run with both configuration surfaces provisioned
so a participant who implements only one surface is still measured
on every behaviour.

### Baseline (13 points across 12 rows)

The C replica must implement the four baseline tools from scratch
plus the two announcement tools the PRD adds. There is no upstream
C reference to inherit. Each row mirrors a P.1 behaviour, executed
against the C binary. C.2.1 (the constructed initialize frame) is
worth 2 points because it asserts the entire handshake contract.

| ID | Points | Description |
|----|--------|-------------|
| C.2.1 | 2 | the hand-written initialize frame (protocolVersion, capabilities, serverInfo) |
| C.2.2 | 1 | `tools/list` exposes all six tools with exact name, description, and schema |
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

The multi-step memory scenarios drive the C binary once under
valgrind with a scripted JSON-RPC sequence. A scenario passes when
valgrind reports zero `definitely lost` and zero `indirectly lost`
bytes and the run completes (no signal exit, leak summary present,
exit code not the error sentinel 99). Each scenario names the
functional rows whose call shapes it exercises in its `gates_on`
tuple; a scenario whose gates have not all passed is recorded as a
zero-point skip rather than driving valgrind on a path that
short-circuits through the participant's error handling.

| ID | Points | Description |
|----|--------|-------------|
| C.5.1 | 2 | session-spanning allocation and free across the full tool surface |
| C.5.2 | 2 | session-state replacement on re-login and idempotent teardown |
| C.5.3 | 2 | leak and responsiveness on the pure baseline regression surface |

### Per-scenario memory sub-assertions (26 points across 26 rows)

Every C functional scenario from C.2.3 through C.4.7 also records a
one-point memory sub-assertion under `<id>.mem` derived from the
same valgrind run that produced the functional verdict. The
sub-assertion is awarded only when the functional row passed AND
valgrind reported a clean leak verdict; a server that fails the
functional contract receives no `.mem` credit, and a leak under a
passing functional row deducts the `.mem` point without affecting
the functional verdict.

The 26 paired ids are: C.2.3 through C.2.12, C.3.1 through C.3.9,
and C.4.1 through C.4.7. The pairing is mechanical (every
behavioural row that runs under valgrind carries a `.mem`); the
single per-row point allocation is the rubric's even weighting of
correctness against leak hygiene on the same execution.

## Expected score upper bounds

| Submission shape | Score |
|---|---|
| No patch (baseline run against the unmodified upstream) | the rubric's deterministic reference; verified at instrument rebuild and reproducible by re-running `python -m grader --no-patch` |
| Python implementation only (no C replica produced) | 30/100 (C.1.1 fails its sole hard gate; every other C row skip-records) |
| Complete correct implementation | 100/100 |

The no-patch numeric is not asserted here because it is a property
of the live grading environment (the unmodified upstream's
behaviour against the seeded mock) and is verified empirically when
the grading VM is rebuilt; this document keeps only the mechanical
maxima that are derivable from the rubric table in
`grader/src/scoring.py` without a live run.
