# BSc APM Case Study - Grader & Parser

Grading suite and transcript parser for the BSc thesis case study comparing [Agentic Project Management (APM)](https://github.com/sdi2200262/agentic-project-management) against [GitHub Spec-kit](https://github.github.io/spec-kit/) for AI-assisted software development.

Three packages, each with its own README:

- **[grader/](grader/)** applies a submission's patch, runs the rubric against the grading environment, and writes a JSON results artefact.
- **[grader-env/](grader-env/)** is the openeclass and mock CAS the grader asserts against, built and released from this repository.
- **[parser/](parser/)** reads Claude Code JSONL transcripts and emits the scope-nested metrics artefacts.

The task spec, participant package, and containerised testing environment ship from [`bsc-apm-case-study-task`](https://github.com/sdi2200262/bsc-apm-case-study-task).

## Documentation

- **[grader/README.md](grader/README.md)** and **[grader/SCORING.md](grader/SCORING.md)**: the grading suite and the rubric it implements.
- **[grader-env/README.md](grader-env/README.md)**: the grading environment, its seed, and how it diverges from the participant mock.
- **[parser/README.md](parser/README.md)**: the transcript parser and its CLI surface.

## Related

- [bsc-apm-thesis](https://github.com/sdi2200262/bsc-apm-thesis): thesis LaTeX source.
- [bsc-apm-case-study-task](https://github.com/sdi2200262/bsc-apm-case-study-task): task specification, participant package, and testing environment.
- [bsc-apm-case-study-data](https://github.com/sdi2200262/bsc-apm-case-study-data): participant submissions.

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).

---

*Part of the BSc APM Case Study evaluating the Agentic Project Management (APM) framework, Department of Informatics and Telecommunications, University of Athens.*
