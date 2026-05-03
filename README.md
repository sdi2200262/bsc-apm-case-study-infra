# BSc APM Case Study - Grader, Parser, Pipeline

Grading suite, transcript parser, and submission processing pipeline for the BSc thesis case study evaluating the [Agentic Project Management (APM)](https://github.com/sdi2200262/agentic-project-management) framework against [GitHub Spec-kit](https://github.github.io/spec-kit/) for AI-assisted software development.

This repository ships three packages:

- **Grader.** Applies a participant's patch on a fresh test branch, runs the rubric phases against the testing environment, and writes a JSON results artefact.
- **Parser.** Reads Claude Code CLI JSONL transcripts produced by participant sessions and emits the canonical scope-nested metrics artefact (economic, time, user input, reliability, supplementary).
- **Pipeline.** Five-stage data-processing pipeline that turns one zipped submission into one row in the aggregated dataset, with per-submission durable artefacts and a manifest audit trail.

The task specification, participant guide and helper skill, and the containerised testing environment the grader runs against ship from the separate [`bsc-apm-case-study-task`](https://github.com/sdi2200262/bsc-apm-case-study-task) repository.

## Repository Structure

```
bsc-apm-case-study-infra/
├── README.md
├── LICENSE
├── grader/                             # Grading suite
│   ├── README.md
│   ├── SCORING.md                      # Rubric the grader implements against
│   ├── seed.yaml                       # Pinned mirror of the testbed's seed
│   ├── __main__.py                     # CLI entry: python -m grader
│   ├── inspect.py                      # Results browser
│   └── src/                            # Phase modules + protocol subpackage
├── parser/                             # Transcript parser
│   ├── README.md
│   └── cc_chat_parser/                 # Claude Code chat parser package
└── pipeline/                           # Submission processing pipeline
    ├── README.md
    ├── PIPELINE.md                     # Submission contract, processing sequence, schemas
    └── *.py
```

## Documentation

- **[grader/README.md](grader/README.md)** - Grading system overview, prerequisites, runtime workflow, pinned references
- **[grader/SCORING.md](grader/SCORING.md)** - Rubric the grader implements against
- **[parser/README.md](parser/README.md)** - Transcript parser overview, CLI surface, environment variables
- **[pipeline/README.md](pipeline/README.md)** - Per-stage CLI usage
- **[pipeline/PIPELINE.md](pipeline/PIPELINE.md)** - Submission contract, processing sequence, output layout, manifest schema, dataset CSV columns

## Related Repositories

- [bsc-apm-thesis](https://github.com/sdi2200262/bsc-apm-thesis) - Thesis LaTeX source
- [bsc-apm-case-study-task](https://github.com/sdi2200262/bsc-apm-case-study-task) - Task specification, participant package, and testing environment
- [bsc-apm-case-study-data](https://github.com/sdi2200262/bsc-apm-case-study-data) - Participant submissions

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).

---

*Part of the BSc APM Case Study evaluating the Agentic Project Management (APM) framework - Department of Informatics and Telecommunications, University of Athens.*
