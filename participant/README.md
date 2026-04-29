# Participant Materials

Everything a study participant receives directly from the research team. The contents of this directory plus the testing environment release tarball (from the [bsc-apm-case-study-env](https://github.com/sdi2200262/bsc-apm-case-study-env) repository) are sufficient to complete a session end to end.

## Contents

| Path | Description |
|------|-------------|
| [`guide/`](guide/) | Participation guide (LaTeX source, compiled PDF, build assets) |
| [`task/PRD.md`](task/PRD.md) | Product Requirements Document; the single source of truth for the implementation |
| [`task/PROMPT.md`](task/PROMPT.md) | Default prompt to start the AI assistant conversation |
| [`scripts/`](scripts/) | Helper scripts for managing Claude Code transcripts during a session |

## Task Overview

*Announcements Functionality and C Replica*

Participants are tasked with:

1. Implementing `get_course_announcements` and `get_general_announcements` tools in the existing Python MCP server, `eclass-mcp-server`.
2. Creating a native C replica of the entire MCP server inside `eclass-mcp-server/c-replica`.

## Key Challenges

- **Legacy-codebase research**: The retrieval logic for the new tools is not present in the existing `eclass-mcp-server`; participants research `openeclass/` to derive the data path their implementations follow.
- **Date filtering**: The new tools accept a `days_back` parameter; participants design and implement the filtering logic and validation rules per the PRD.
- **C implementation**:
    - Manual JSON-RPC 2.0 framing, parsing, and serialisation; no JSON-parsing library is permitted.
    - Networking and HTML or XML parsing through the libraries the PRD names.
- **Memory safety**: The C replica must be free of detectable leaks under `valgrind` across its supported tool-session surface.

## Helper Scripts

The three Python scripts in [`scripts/`](scripts/) manage Claude Code transcripts. Each script accepts the workspace path as its positional argument and resolves it to the corresponding entry under `~/.claude/projects/`.

| Script | Purpose |
|--------|---------|
| `list-chats.py` | List transcripts in a workspace's project directory with first and last record timestamps and a preview of the first user message. |
| `collect-chats.py` | Copy transcripts whose first record timestamp falls in a given ISO time range into `<workspace>/transcripts/`. |
| `reset-chats.py` | Delete every transcript in a workspace's project directory. Destructive; prompts for confirmation by default. |

Run any script with `--help` for usage and examples.

## Related

- [Participation guide](guide/) - the document participants follow end to end
- [Grading suite](../grader/) - how submissions are evaluated
- [Scoring rubric](../grader/SCORING.md) - point allocation per requirement
