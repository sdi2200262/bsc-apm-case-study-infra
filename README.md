# BSc APM Case Study - Grader, Parser, Pipeline

Grading suite, transcript parser, and submission pipeline for the BSc thesis case study comparing [Agentic Project Management (APM)](https://github.com/sdi2200262/agentic-project-management) against [GitHub Spec-kit](https://github.github.io/spec-kit/) for AI-assisted software development.

Three packages:

- **Grader.** Applies a submission's patch, runs the rubric against the testing environment, writes a JSON results artefact.
- **Parser.** Reads Claude Code JSONL transcripts and emits the scope-nested metrics artefact.
- **Pipeline.** Turns one zipped submission into one dataset row, with per-submission artefacts and a manifest trail.

The task spec, participant package, and containerised testing environment ship from [`bsc-apm-case-study-task`](https://github.com/sdi2200262/bsc-apm-case-study-task).

## Repository Structure

See each package's own README for detail.

```
bsc-apm-case-study-infra/
├── README.md
├── LICENSE
├── grader/         # Grading suite (python -m grader)
├── grader-env/     # Containerised testing environment build
├── parser/         # Transcript parser
└── pipeline/       # Submission processing pipeline
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
