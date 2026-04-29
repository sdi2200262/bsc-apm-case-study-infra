# BSc APM Case Study - Task, Grader & Participant Guides

The task specification, grading suite and participant guides for the BSc Thesis Case Study evaluating the [Agentic Project Management (APM)](https://github.com/sdi2200262/agentic-project-management) framework against other approaches in AI-assisted software development.

## Task Summary

*Announcements Functionality and C Replica*

Participants implement new announcement tools (`get_course_announcements` and `get_general_announcements`) in a Python MCP server and create a high-performance C replica. Submissions are evaluated using an automated grading pipeline that runs against a separately-installed testing environment (the [`bsc-apm-case-study-env`](https://github.com/sdi2200262/bsc-apm-case-study-env) package).

## Scoring

Total: **100 points**

| Category | Points | Description |
|----------|--------|-------------|
| Python Baseline | 12 | Existing functionality (must not break) |
| Python Features | 36 | `get_course_announcements` and `get_general_announcements` |
| C Replica | 52 | Full C implementation with memory safety |

See [grader/SCORING.md](grader/SCORING.md) for the detailed rubric.

## Repository Structure

```
bsc-apm-case-study-task/
├── README.md
├── LICENSE
├── grader/                             # Grading suite
│   ├── README.md
│   ├── SCORING.md                      # rubric
│   ├── seed.yaml                       # pinned mirror of the env package's seed
│   ├── __main__.py                     # CLI entry: python -m grader
│   ├── inspect.py                      # results browser
│   └── src/                            # phase modules + protocol subpackage
├── parser/                             # Transcript parser
│   ├── README.md
│   └── cc_chat_parser/                 # Claude Code chat parser package
├── pipeline/                           # Data processing pipeline
│   ├── README.md
│   ├── PIPELINE.md
│   └── *.py
└── participant/                        # Participant-facing materials
    ├── README.md
    ├── guide/                          # Study guide (LaTeX source, PDF, assets)
    ├── scripts/                        # Helper scripts shipped to participants
    └── task/                           # Task specification
        ├── PRD.md
        └── PROMPT.md
```

## Documentation

- **[participant/README.md](participant/README.md)** - Participant materials overview, including the task specification
- **[grader/README.md](grader/README.md)** - Grading system overview, prerequisites, runtime workflow, and pinned references
- **[grader/SCORING.md](grader/SCORING.md)** - Rubric the grader implements against
- **[parser/README.md](parser/README.md)** - Transcript parser overview
- **[pipeline/README.md](pipeline/README.md)** - Pipeline scripts
- **[pipeline/PIPELINE.md](pipeline/PIPELINE.md)** - Pipeline protocol
- **[participant/guide/README.md](participant/guide/README.md)** - Guide building

## Related Repositories

- [bsc-apm-thesis](https://github.com/sdi2200262/bsc-apm-thesis) - Thesis LaTeX source
- [bsc-apm-case-study-env](https://github.com/sdi2200262/bsc-apm-case-study-env) - Participant testing environment the grader runs against
- [bsc-apm-case-study-data](https://github.com/sdi2200262/bsc-apm-case-study-data) - Participant submissions (private)

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).

---

*Part of BSc Thesis Case Study evaluating the Agentic Project Management (APM) framework - Department of Informatics and Telecommunications, University of Athens.*
