# Task Specification

This directory contains the task specification materials provided to participants.

## Contents

| File | Description |
|------|-------------|
| [PRD.md](PRD.md) | Product Requirements Document - the single source of truth |
| [Prompt.md](Prompt.md) | Default prompt to start AI assistant conversations |

## Task Overview

*Announcements Functionality and C Replica*

Participants are tasked with:
1. Implementing `get_course_announcements` and `get_general_announcements` tools in the existing Python MCP server: `eclass-mcp-server`
2. Creating a native C replica of the entire MCP server inside `eclass-mcp-server/c-replica`

## Key Challenges

- **Legacy-codebase research**: The retrieval logic for the new tools is not present in the existing `eclass-mcp-server`; participants research `openeclass/` to derive the data path their implementations follow.
- **Date filtering**: The new tools accept a `days_back` parameter; participants design and implement the filtering logic and validation rules per the PRD.
- **C implementation**:
    - Manual JSON-RPC 2.0 framing, parsing, and serialisation; no JSON-parsing library is permitted.
    - Networking and HTML/XML parsing through the libraries the PRD names.
- **Memory safety**: The C replica must be free of detectable leaks under `valgrind` across its supported tool-session surface.

## Usage

Participants receive these files alongside their [participant guide](../participant/guide/) and use them to drive their AI-assisted implementation sessions.

## Related

- [Grading Suite](../grader/) - Automated testing against this specification
- [Scoring Rubric](./SCORING.md) - Point allocation for each requirement
