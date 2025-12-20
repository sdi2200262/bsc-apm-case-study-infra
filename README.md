# BSc APM Case Study - Task, Grader & Participant Guides

The task specification, grading suite and participant guides for the BSc Thesis Case Study evaluating the [Agentic Project Management (APM)](https://github.com/sdi2200262/agentic-project-management) framework against other approaches in AI-assisted software development.

## Current Task Version

**Version 1.0.0** - *Get Course Announcements and C Replica*

The task requires participants to implement new functionality in a Python MCP server and create a high-performance C replica. Submissions are evaluated using an automated grading pipeline that replicates participant's working environment.

## Scoring

Total: **48 points**

| Category | Points | Description |
|----------|--------|-------------|
| Python Baseline | 12 | Existing functionality (must not break) |
| Python Feature | 12 | `get_course_announcements` implementation |
| C Replica | 24 | Full C implementation with memory safety |

See [task/SCORING.md](SCORING.md) for the detailed rubric.

## Overview

This repository consolidates:
- **Task Specification** - The PRD and Default Prompt provided to participants
- **Grading Suite** - Black-box testing infrastructure for evaluating submissions
- **Participant Guides** - LaTeX guide for study participants

## Repository Structure

```
bsc-apm-case-study-task/
├── README.md                       
├── LICENSE                             # GPL-3.0-or-later
├── task/                               # Task specification materials
│   ├── README.md
|   ├── SCORING.md                      # Scoring rubric (48 points total)
│   ├── Specification.md                # Product Requirements Document (PRD)
│   └── Default-Prompt.md               # Default prompt for AI assistants
├── grader/                             # Grading infrastructure
│   ├── README.md
│   ├── SETUP.md                        # Environment setup instructions
│   ├── grade                           # Entry point script
│   ├── docker-compose.eclass.yaml  
│   ├── src/                            # Grading modules
│   ├── fixtures/                       # HTML fixtures for SSO mock
│   └── scripts/                        # Utility scripts
└── participant-guides/                 # Study participation guides
    ├── README.md
    ├── latexmkrc                       # LaTeX build configuration
    ├── participant_guide_copilot.tex
    ├── participant_guide_copilot.pdf
    ├── participant_guide_cursor.tex
    ├── participant_guide_cursor.pdf
    └── build/                          # LaTeX auxiliary files
```

## Related Repositories

- [bsc-apm-thesis](https://github.com/sdi2200262/bsc-apm-thesis) - Thesis LaTeX source
- [bsc-apm-case-study-data](https://github.com/sdi2200262/bsc-apm-case-study-data) - Participant submissions (private)

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).

---

*Part of BSc Thesis Case Study evaluating the Agentic Project Management (APM) framework - Department of Informatics and Telecommunications, University of Athens.*
