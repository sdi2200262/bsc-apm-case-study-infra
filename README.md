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

See [task/SCORING.md](task/SCORING.md) for the detailed rubric.

## Repository Structure

```
bsc-apm-case-study-task/
├── README.md
├── LICENSE
├── task/                               # Task specification
│   ├── README.md
│   ├── SCORING.md
│   ├── PRD.md
│   └── Prompt.md
├── grader/                             # Grading suite
│   ├── README.md
│   ├── SETUP.md
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
└── participant-guides/                 # Study guides
    ├── README.md
    └── *.tex, *.pdf, assets/
```

## Documentation

- **[task/README.md](task/README.md)** - Task specification overview
- **[grader/README.md](grader/README.md)** - Grading system overview
- **[grader/SETUP.md](grader/SETUP.md)** - Environment setup
- **[parser/README.md](parser/README.md)** - Transcript parser overview
- **[pipeline/README.md](pipeline/README.md)** - Pipeline scripts
- **[pipeline/PIPELINE.md](pipeline/PIPELINE.md)** - Pipeline protocol
- **[participant-guides/README.md](participant-guides/README.md)** - Guide building

## Related Repositories

- [bsc-apm-thesis](https://github.com/sdi2200262/bsc-apm-thesis) - Thesis LaTeX source
- [bsc-apm-case-study-env](https://github.com/sdi2200262/bsc-apm-case-study-env) - Participant testing environment the grader runs against
- [bsc-apm-case-study-data](https://github.com/sdi2200262/bsc-apm-case-study-data) - Participant submissions (private)

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).

---

*Part of BSc Thesis Case Study evaluating the Agentic Project Management (APM) framework - Department of Informatics and Telecommunications, University of Athens.*
