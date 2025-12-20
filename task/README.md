# Task Specification

This directory contains the task specification materials provided to participants.

## Contents

| File | Description |
|------|-------------|
| [Specification.md](Specification.md) | Product Requirements Document (PRD) - the single source of truth |
| [Default-Prompt.md](Default-Prompt.md) | Default prompt to start AI assistant conversations |

## Task Overview

*Get Course Announcements and C Replica*

Participants are tasked with:
1. Implementing a new `get_course_announcements` tool in the existing Python MCP server: `eclass-mcp-server`
2. Creating a native C replica of the entire MCP server inside `eclass-mcp-server/c-replica`

## Key Challenges

- **Dynamic Data Source**: Requires research of a legacy codebase (`openeclass/`) to discover unique AJAX endpoints
- **Client-Side Filtering**: The legacy codebase does not support date filtering - participants must implement robust client-side logic
- **C Implementation**: 
    - Manual MCP (JSON-RPC 2.0) protocol implementation (no external JSON libraries)
    - Specific library requirements for HTTPS protocol management and HTML parsing
- **Memory Safety**: C implementation must pass Valgrind checks with 0 direct and indirect memory leaks

## Usage

Participants receive these files alongside their [participant guide](../participant-guides/) and use them to drive their AI-assisted implementation sessions.

## Related

- [Grading Suite](../grader/) - Automated testing against this specification
- [Scoring Rubric](./SCORING.md) - Point allocation for each requirement
