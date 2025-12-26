# BSc APM Case Study - Task, Grader & Participant Guides

The task specification, grading suite and participant guides for the BSc Thesis Case Study evaluating the [Agentic Project Management (APM)](https://github.com/sdi2200262/agentic-project-management) framework against other approaches in AI-assisted software development.

## Task Summary

*Get Course Announcements and C Replica*

Participants implement new functionality in a Python MCP server (`get_course_announcements` tool) and create a high-performance C replica. Submissions are evaluated using an automated grading pipeline that replicates the participant's working environment.

## Scoring

Total: **48 points**

| Category | Points | Description |
|----------|--------|-------------|
| Python Baseline | 12 | Existing functionality (must not break) |
| Python Feature | 12 | `get_course_announcements` implementation |
| C Replica | 24 | Full C implementation with memory safety |

See [task/SCORING.md](task/SCORING.md) for the detailed rubric.

## Repository Structure

```
bsc-apm-case-study-task/
├── README.md
├── LICENSE
├── task/                               # Task specification
│   ├── README.md
│   ├── SCORING.md
│   ├── Specification.md
│   └── Default-Prompt.md
├── grader/                             # Grading infrastructure
│   ├── README.md
│   ├── SETUP.md
│   ├── PIPELINE.md
│   ├── grade
│   ├── docker-compose.eclass.yaml
│   ├── src/                            # Core grading modules
│   ├── pipeline/                       # Data processing pipeline
│   │   ├── README.md
│   │   └── *.py
│   ├── scripts/                        # Utility scripts
│   │   ├── README.md
│   │   └── *.py
│   └── fixtures/                       # SSO mock fixtures
│       ├── README.md
│       └── *.html
└── participant-guides/                 # Study guides
    ├── README.md
    └── *.tex, *.pdf, assets/
```

## Documentation

- **[task/README.md](task/README.md)** - Task specification overview
- **[grader/README.md](grader/README.md)** - Grading system overview
- **[grader/SETUP.md](grader/SETUP.md)** - Environment setup
- **[grader/PIPELINE.md](grader/PIPELINE.md)** - Pipeline protocol
- **[grader/pipeline/README.md](grader/pipeline/README.md)** - Pipeline scripts
- **[grader/scripts/README.md](grader/scripts/README.md)** - Utility scripts
- **[grader/fixtures/README.md](grader/fixtures/README.md)** - SSO fixtures
- **[participant-guides/README.md](participant-guides/README.md)** - Guide building

## Related Repositories

- [bsc-apm-thesis](https://github.com/sdi2200262/bsc-apm-thesis) - Thesis LaTeX source
- [bsc-apm-case-study-data](https://github.com/sdi2200262/bsc-apm-case-study-data) - Participant submissions (private)

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).

---

*Part of BSc Thesis Case Study evaluating the Agentic Project Management (APM) framework - Department of Informatics and Telecommunications, University of Athens.*
