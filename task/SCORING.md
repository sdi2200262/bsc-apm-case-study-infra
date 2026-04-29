# Scoring Rubric

Total: 100 points

The grader is a JSON-RPC black box: it observes only the `text` content of
each tool response and scores against the assertions tabulated below.
Strict tests assert exact equality with the response text. Implementation
tests assert the `Found N announcement(s):` substring with a seed-derived
`N` plus the verbatim body string of every in-scope announcement. Anchor
tests add multi-attribute checks (source attribution; multi-probe
differentials). Across all implementation tests, `days_back=N` is
interpreted inclusively against a calendar-based cutoff at midnight of
`(today − N days)`: an announcement whose timestamp falls at or after
that cutoff is in scope.

## Python Implementation (41 points)

### Baseline (10 points)

The four tools `login`, `logout`, `get_courses`, `authstatus` already
exist in the upstream `eclass-mcp-server` reference. The participant
inherits working implementations and must not break them while adding
`get_course_announcements` and `get_general_announcements` to the
server. P.1.1 confirms the protocol handshake and the registration
of every tool the rubric grades; the remaining nine rows confirm the
four pre-existing tools' behaviour against the seeded user
(`student1`) and the three enrolled courses (`CS101`, `PHYS150`,
`MATH201`).

| ID | Points | Description |
|----|--------|-------------|
| P.1.1 | 1 | `initialize` shape and `tools/list` return all six tools |
| P.1.2 | 1 | Login with valid credentials succeeds |
| P.1.3 | 1 | Second login while authenticated reports already-logged-in |
| P.1.4 | 1 | Login with empty credentials reports the missing-credentials error |
| P.1.5 | 1 | Logout while authenticated succeeds |
| P.1.6 | 1 | Logout without prior login is a no-op |
| P.1.7 | 1 | `get_courses` while authenticated returns the three enrolled courses |
| P.1.8 | 1 | `get_courses` without authentication reports not-logged-in |
| P.1.9 | 1 | `authstatus` while authenticated reports logged-in with the username |
| P.1.10 | 1 | `authstatus` without authentication reports not-logged-in |

### Feature: Course Announcements (17 points)

The new tool `get_course_announcements` fetches a single course's
announcements and applies a client-side `days_back` filter. The seeded
test course `CS101` carries four announcements at days_ago 0, 15, 30, 60;
the empty course `MATH201` carries none. The per-course endpoint applies
no backend date floor, so every announcement is visible to a client and
all filtering is the participant's responsibility. Each window-size step
adds exactly one in-scope announcement, so the expected count grows
monotonically with `days_back`.

| ID | Points | Description |
|----|--------|-------------|
| P.2.1 | 1 | Strict: not logged in returns the standard not-logged-in error |
| P.2.2 | 1 | Strict: an unparseable `course_url` returns `"Error: Could not extract course code."` |
| P.2.3 | 1 | Strict: a negative `days_back` returns `"Error: days_back must be a positive integer."` |
| P.2.4 | 1 | Strict: MATH201 with default `days_back` returns `"No announcements found."` |
| P.2.5 | 3 | Implementation: `days_back=0` returns the day-zero announcement only (count = 1) |
| P.2.6 | 3 | Implementation: `days_back=15` returns the two in-scope announcements (count = 2) |
| P.2.7 | 4 | Anchor: default `days_back=30` returns the three in-scope announcements (count = 3) |
| P.2.8 | 3 | Implementation: `days_back=60` returns all four announcements (count = 4); catches reliance on a backend cap that the per-course endpoint does not enforce |

### Feature: General Announcements (14 points)

The new tool `get_general_announcements` aggregates system-wide and
course-specific announcements into a single response with source
attribution. The endpoint that fans these out (`myannouncements.php`)
applies a hardcoded 30-day backend floor and filters to the user's
enrolled courses; the participant's `days_back` is therefore valid only
within `[0, 30]` and never reaches non-enrolled courses. Within that
window the seed places three admin announcements (days_ago 0, 15, 30),
three `CS101` announcements (0, 15, 30), and three `PHYS150` announcements
(0, 15, 30), totalling nine. Each window-size step adds three in-scope
announcements (one admin + one `CS101` + one `PHYS150`), so the expected
count grows by three per step.

| ID | Points | Description |
|----|--------|-------------|
| P.3.1 | 1 | Strict: not logged in returns the standard not-logged-in error |
| P.3.2 | 1 | Strict: a negative `days_back` returns `"Error: days_back must be a positive integer."` |
| P.3.3 | 1 | Strict: `days_back=31` returns `"Error: Cannot retrieve announcements older than 30 days."` |
| P.3.4 | 3 | Implementation: `days_back=0` returns the three day-zero announcements (count = 3) |
| P.3.5 | 3 | Implementation: `days_back=15` returns the six in-scope announcements (count = 6) |
| P.3.6 | 5 | Anchor: default `days_back=30` returns the nine in-scope announcements (count = 9) with `Source: System` present and at least two distinct course-source attributions present |

## C Replica Implementation (59 points)

### Build and Technical Stack (5 points)

The C implementation is a separate program living under
`eclass-mcp-server/c-replica/`. It is built by a participant-supplied
`Makefile` and invoked by the grader as a subprocess. The technical
stack constraint is: `libcurl` and `libxml2` are required; no JSON-parsing
library is permitted; the participant parses JSON-RPC manually. Standard
system runtime libraries and the transitive system dependencies of
`libcurl` and `libxml2` are unrestricted.

| ID | Points | Description |
|----|--------|-------------|
| C.1.1 | 3 | `make c-server` exits 0 and produces the `server` binary |
| C.1.2 | 2 | `ldd server` lists `libcurl.so` and `libxml2.so` among its dependencies, and lists no library whose SO name matches the forbidden JSON-parsing patterns: any name beginning with `libjson`, `libcjson`, `libjansson`, `libyajl`, `libjq`, or `libparson` |

### Baseline (10 points)

The C replica must implement the four baseline tools from scratch. There
is no upstream C reference to inherit. Each row below mirrors a P.1
behaviour, executed against the C binary instead of the Python server.

| ID | Points | Description |
|----|--------|-------------|
| C.2.1 | 1 | `initialize` shape and `tools/list` return all six tools |
| C.2.2 | 1 | Login with valid credentials succeeds |
| C.2.3 | 1 | Second login while authenticated reports already-logged-in |
| C.2.4 | 1 | Login with empty credentials reports the missing-credentials error |
| C.2.5 | 1 | Logout while authenticated succeeds |
| C.2.6 | 1 | Logout without prior login is a no-op |
| C.2.7 | 1 | `get_courses` while authenticated returns the three enrolled courses |
| C.2.8 | 1 | `get_courses` without authentication reports not-logged-in |
| C.2.9 | 1 | `authstatus` while authenticated reports logged-in with the username |
| C.2.10 | 1 | `authstatus` without authentication reports not-logged-in |

### Feature: Course Announcements (17 points)

Mirror of P.2 against the C binary. The seed values, boundary semantics,
and assertion style match the Python feature section above; the only
difference is which executable serves the JSON-RPC.

| ID | Points | Description |
|----|--------|-------------|
| C.3.1 | 1 | Strict: not logged in returns the standard not-logged-in error |
| C.3.2 | 1 | Strict: an unparseable `course_url` returns the extract-course-code error |
| C.3.3 | 1 | Strict: a negative `days_back` returns the positive-integer error |
| C.3.4 | 1 | Strict: MATH201 with default `days_back` returns the no-announcements message |
| C.3.5 | 3 | Implementation: `days_back=0` returns the day-zero announcement only |
| C.3.6 | 3 | Implementation: `days_back=15` returns the two in-scope announcements |
| C.3.7 | 4 | Anchor: default `days_back=30` returns the three in-scope announcements |
| C.3.8 | 3 | Implementation: `days_back=60` returns all four announcements |

### Feature: General Announcements (14 points)

Mirror of P.3 against the C binary. Seed values, the backend's 30-day
floor, the enrollment filter, and the assertion style match the Python
feature section above.

| ID | Points | Description |
|----|--------|-------------|
| C.4.1 | 1 | Strict: not logged in returns the standard not-logged-in error |
| C.4.2 | 1 | Strict: a negative `days_back` returns the positive-integer error |
| C.4.3 | 1 | Strict: `days_back=31` returns the older-than-30-days error |
| C.4.4 | 3 | Implementation: `days_back=0` returns the three day-zero announcements |
| C.4.5 | 3 | Implementation: `days_back=15` returns the six in-scope announcements |
| C.4.6 | 5 | Anchor: default `days_back=30` returns the nine in-scope announcements with `Source: System` and at least two distinct course-source attributions present |

### Memory (13 points)

Each scenario runs the C binary under
`valgrind --leak-check=full --error-exitcode=99` driven by a scripted
JSON-RPC client. A scenario passes when the run finishes with zero
definitely-lost bytes, zero indirectly-lost bytes, and exit 0. The
scenarios cover, in order, session-state allocations, per-tool
allocations across argument variations on each feature tool, and
inter-tool state across a realistic full-session sequence; the
integration scenario carries anchor weight because it exercises the
largest cross-tool surface.

| ID | Points | Description |
|----|--------|-------------|
| C.5.1 | 3 | Login lifecycle: login → login (already-logged-in) → logout → logout (no-op) → login → logout |
| C.5.2 | 3 | Course-announcement variations: login → get_courses → four `get_course_announcements` calls (CS101 default, MATH201 default, CS101 `days_back=0`, CS101 `days_back=60`) → logout |
| C.5.3 | 3 | General-announcement variations: login → get_courses → three `get_general_announcements` calls (default, `days_back=0`, `days_back=15`) → logout |
| C.5.4 | 4 | Anchor: full lifecycle integration with both features. login → get_courses → get_course_announcements (CS101 default) → get_course_announcements (CS101 `days_back=60`) → get_course_announcements (MATH201 default) → get_general_announcements (default) → get_general_announcements (`days_back=15`) → get_general_announcements (`days_back=0`) → authstatus → logout → login → get_course_announcements (CS101 `days_back=0`) → get_general_announcements (`days_back=15`) → logout |

## Expected Scores

| Submission Type | Python Baseline | Python Features | C Replica | Total |
|-----------------|-----------------|-----------------|-----------|-------|
| No patch (baseline only) | 9/10 | 0/31 | 0/59 | 9/100 |
| Python implementation only | 10/10 | 31/31 | 0/59 | 41/100 |
| Complete implementation | 10/10 | 31/31 | 59/59 | 100/100 |

The no-patch row earns nine of ten on Python baseline because
P.1.1 (which confirms `tools/list` registers all six tools) requires
the patch's tool additions; the other nine baseline rows already
pass against the upstream reference.
