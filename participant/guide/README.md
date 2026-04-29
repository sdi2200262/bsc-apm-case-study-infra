# Participant Guides

LaTeX source and compiled PDF for the study participant documentation.

## Contents

| File | Description |
|------|-------------|
| `participant-guide-copilot.tex` | Participant guide (GitHub Copilot) - LaTeX source |
| `participant-guide-copilot.pdf` | Participant guide (GitHub Copilot) - compiled PDF |
| `latexmkrc` | LaTeX build configuration |
| `assets/` | LaTeX build assets |
| `build/` | LaTeX auxiliary files (gitignored) |

## Building the PDF

Auxiliary files are output to `build/` to keep the directory clean. The PDF is automatically copied to the root after compilation.

```bash
latexmk -pdf participant-guide-copilot.tex
```

To clean auxiliary files:

```bash
latexmk -c
```

## Related

- [Task Specification](../task/) - The PRD provided to participants
- [Grading Suite](../grader/) - How submissions are evaluated
