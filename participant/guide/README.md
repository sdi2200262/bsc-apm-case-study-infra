# Participant Guide

LaTeX source and compiled PDF for the study participant documentation.

## Contents

| File | Description |
|------|-------------|
| `participant-guide-cc.tex` | Participant guide (Claude Code) - LaTeX source |
| `participant-guide-cc.pdf` | Participant guide (Claude Code) - compiled PDF |
| `latexmkrc` | LaTeX build configuration |
| `assets/` | LaTeX build assets |
| `build/` | LaTeX auxiliary files (gitignored) |

## Building the PDF

Auxiliary files are output to `build/` to keep the directory clean. The PDF is copied to the root after compilation.

```bash
latexmk -pdf participant-guide-cc.tex
```

To clean auxiliary files:

```bash
latexmk -c
```

## Related

- [Task specification](../task/) - the PRD and prompt
- [Participant materials overview](../README.md) - everything participants receive
- [Grading suite](../../grader/) - how submissions are evaluated
