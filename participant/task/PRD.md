# Product Requirements Document: eClass MCP Server Enhancement and Native C Replica

This document specifies the goals, functional requirements, and
acceptance criteria for expanding the capabilities of the
`eclass-mcp-server` and producing a native C replica of the
service.

## 1. Overview

**Background.** The `eclass-mcp-server` is a Python service that
integrates with the `openeclass` platform (a PHP codebase) over
the Model Context Protocol. The current Python server exposes
four tools: `login`, `logout`, `get_courses`, and `authstatus`.
Two announcement tools must be added on top of this baseline:
`get_course_announcements` and `get_general_announcements`.

**Environment.** The `eclass-mcp-server` and `openeclass`
checkouts in the workspace are intentionally pinned to a specific
commit and release respectively.

**Objective.** Two deliverables:

1. **Feature expansion.** Implement the two new announcement
   tools in the existing Python codebase.
2. **Native replication.** Produce a standalone C microservice at
   `eclass-mcp-server/c-replica/` that exposes all six tools (the
   four pre-existing baseline tools plus the two new announcement
   tools) and acts as a functional drop-in replacement for the
   Python server: under identical inputs, its JSON-RPC text
   content matches the Python server's.

The deliverable scope is the runtime feature surface (the Python
modules added to `eclass-mcp-server/` and the C binary at
`eclass-mcp-server/c-replica/server`). Updates to the existing
reference documentation under `eclass-mcp-server/docs/` are not
required, and no unit-test or testing-logic artefacts are part of
the deliverable.

## 2. Announcement Tools Implementation

### Tool: `get_course_announcements`

Fetches announcements for a single course, optionally filtered by
recency.

**Input schema.**

```json
{
  "type": "object",
  "properties": {
    "course_url": {
      "type": "string",
      "description": "The course URL as exposed by get_courses."
    },
    "days_back": {
      "type": "integer",
      "description": "Number of days back to include. Zero is valid and returns today's announcements only. Default is 30."
    }
  },
  "required": ["course_url"]
}
```

**Output.** A single `types.TextContent` object whose text is one
of the strings defined in §5.

On success with one or more announcements inside the requested
window, the format is:

```
Found <N> announcement(s):

1. <Announcement Title>
    Date: <Date String>
    Content: <Full Announcement Body>

2. ...
```

`<N>` is the count of announcements that fall inside the window.
The body string is the announcement's text content, rendered as
plain text after stripping HTML tags and normalising whitespace.

**Date filter semantics.** `days_back=N` includes every
announcement whose timestamp is no older than `N` days from the
current calendar day. An announcement timestamped exactly `N`
days ago is in the window; one timestamped `N+1` days ago is not.

**Validation.** `days_back` must be a non-negative integer.
Negative values error per §5. The tool itself imposes no upper
bound on `days_back`.

### Tool: `get_general_announcements`

Returns a unified view of the platform's system-wide
announcements together with announcements from the authenticated
user's enrolled courses, with source attribution on each entry.

**Input schema.**

```json
{
  "type": "object",
  "properties": {
    "days_back": {
      "type": "integer",
      "description": "Number of days back to include. Zero is valid and returns today's announcements only. Default is 30."
    }
  }
}
```

**Output.** A single `types.TextContent` object whose text is one
of the strings defined in §5. On success the format is:

```
Found <N> announcement(s):

1. <Announcement Title>
    Source: <attribution>
    Date: <Date String>
    Content: <Full Announcement Body>

2. ...
```

**Source attribution.** Each entry carries a `Source:` line. An
announcement that originates from the platform itself (a
system-wide announcement) is attributed as `Source: System`. An
announcement that originates from a course is attributed using
that course's code (the same identifier `get_courses` exposes),
formatted as `Source: <code>`.

**Date filter semantics.** Same calendar-day-based inclusion rule
as the per-course tool.

**Validation.** `days_back` must be in the range `[0, 30]`.
Values outside this range error per §5.

## 3. Native C Replica Implementation

The C implementation lives at `eclass-mcp-server/c-replica/` and
exposes the same six tools, with the same input schemas, the same
output formats, and the same error strings as the Python server.

### Configuration

The C server reads its configuration from the same environment
variables the Python server already reads. One `.env` file at the
`eclass-mcp-server/` package root serves both implementations; no
C-only configuration surface is introduced.

### Architectural constraints

The C binary adheres to a strict technical stack:

- **Language.** C99 or C11.
- **Compiler.** GCC 9.0 or newer (or a compatible C11-supporting
  compiler).
- **Networking.** `libcurl` (minimum 7.81.0); the cookie engine
  carries the SSO session across redirects.
- **HTML and XML parsing.** `libxml2` (minimum 2.9.13); used to
  strip tags and normalise whitespace so body strings match the
  Python implementation's textually.
- **JSON and protocol.** JSON-RPC 2.0 framing, parsing, and
  serialisation are implemented manually using standard C string
  facilities. No external JSON-parsing library is permitted; the
  C binary's dynamically-linked dependency list must not include
  any JSON-parsing library.

### Memory safety

The binary is leak-free under `valgrind --leak-check=full` across
the supported tool-session surface. All `libcurl` handles and
`libxml2` contexts are explicitly freed.

### Runtime behavior

The C microservice is a CLI application implementing the Model
Context Protocol's stdio transport.

- **Execution.** The binary runs without command-line arguments
  (`./server`). All configuration comes from environment
  variables.
- **stdin.** Newline-delimited JSON-RPC requests.
- **stdout.** Newline-delimited JSON-RPC responses. stdout
  carries protocol traffic only; any other output on stdout
  corrupts the protocol.
- **Lifecycle.** The server processes requests in a loop until
  the input stream closes (EOF).
- **Responsiveness.** Every JSON-RPC request emits a response.
  Implementations that hang, deadlock, or fail to respond are
  considered non-functional.

### Protocol compliance

The JSON-RPC handshake (`initialize`, `tools/list`, `tools/call`
framing) and the wire-level shape of the four pre-existing tools
are documented in
`eclass-mcp-server/docs/reference/wire-protocol.md`; per-tool
contracts for those four tools (input schemas, response
behaviour, error handling) are documented in
`eclass-mcp-server/docs/reference/tools-reference.md`. The two
new announcement tools follow the same framing convention; their
per-tool contracts are defined in §2 and §5 of this document.

## 4. Cross-cutting Requirements

### Authentication

All six tools require an authenticated session.

- **Python.** Reuses the existing session model; tool entry
  points return the not-logged-in error string from §5 when no
  session is active.
- **C replica.** Maintains a persistent session state equivalent
  to the Python version, including session cookies across tool
  calls.

### Data source

The retrieval logic for the announcement tools is not present in
the existing `eclass-mcp-server`. The implementation derives the
data path through research of the `openeclass` codebase shipped
in the workspace.

### Date filtering

Tool implementations parse the locale-specific date strings the
underlying platform renders and apply the inclusive calendar-day
filter defined in §2.

## 5. Acceptance Criteria

All subsequent evaluation of the deliverables runs against a
containerized instance of the same pinned `openeclass` release.

The textual contracts below are checked verbatim. Deviations in
punctuation, wording, or whitespace fail validation.

### Tool: `get_course_announcements`

| Condition | Response text |
|---|---|
| Not logged in | `Error: Not logged in. Please log in first using the login tool.` |
| Unparseable `course_url` | `Error: Could not extract course code.` |
| `days_back` is negative | `Error: days_back must be a positive integer.` |
| Window is empty | `No announcements found.` |
| Window is non-empty | The §2 success format with `<N>` equal to the count of announcements in the window. |

### Tool: `get_general_announcements`

| Condition | Response text |
|---|---|
| Not logged in | `Error: Not logged in. Please log in first using the login tool.` |
| `days_back` is negative | `Error: days_back must be a positive integer.` |
| `days_back` is greater than 30 | `Error: Cannot retrieve announcements older than 30 days.` |
| Window is empty | `No announcements found.` |
| Window is non-empty | The §2 success format. The response renders `Source: System` for each system-wide entry and `Source: <code>` (where `<code>` is the course code from `get_courses`) for each course entry. |

### C replica system behavior

| Aspect | Criterion |
|---|---|
| Compilation | `make c-server` from `c-replica/` exits 0 and produces `c-replica/server`. |
| Tech stack | The dynamically-linked dependencies of `c-replica/server` include `libcurl` and `libxml2` and exclude any JSON-parsing library. |
| Protocol | `initialize`, `tools/list`, and `tools/call` responses match the framing convention referenced in §3. |
| Authentication | Performs the full SSO login flow against the configured target; subsequent tool calls reuse the session. |
| Cookie state | `authstatus` reflects the login state set by the most recent `login` call. |
| Memory | Cleanly under `valgrind --leak-check=full` with zero definitely-lost and zero indirectly-lost bytes across the supported tool-session surface. |
| Responsiveness | Every JSON-RPC request emits a response; no hangs or deadlocks. |

## 6. Deliverables

### Python implementation

- **Location.** `eclass-mcp-server/`
- **Artefacts.** The complete updated Python project, including
  any modified or new modules required for the two announcement
  tools.

### C replica implementation

- **Location.** `eclass-mcp-server/c-replica/`
- **Artefacts.**
  - Source files (`.c`) and headers (`.h`).
  - A `Makefile` whose `c-server` target compiles the source and
    produces a binary named `server` in the same directory. The
    target links against the libraries the technical-stack
    section names and against no JSON-parsing library.
