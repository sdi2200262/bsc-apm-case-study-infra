# Participant Guides

LaTeX source and compiled PDFs for study participant documentation.

## Sub-Studies

- **Sub-Study A (Cursor)**: Quantitative economic analysis - measures token consumption and cost
- **Sub-Study B (GitHub Copilot)**: Qualitative process analysis - measures interaction patterns and user burden

## Contents

| File | Description |
|------|-------------|
| `participant_guide_copilot.tex` | Sub-Study B guide (GitHub Copilot) - LaTeX source |
| `participant_guide_copilot.pdf` | Sub-Study B guide (GitHub Copilot) - compiled PDF |
| `participant_guide_cursor.tex` | Sub-Study A guide (Cursor) - LaTeX source |
| `participant_guide_cursor.pdf` | Sub-Study A guide (Cursor) - compiled PDF |
| `latexmkrc` | LaTeX build configuration |
| `assets/` | LaTeX build assets |
| `build/` | LaTeX auxiliary files (gitignored) |

## Building PDFs

Auxiliary files are output to `build/` to keep the directory clean. PDFs are automatically copied to the root after compilation.

```bash
latexmk -pdf participant_guide_copilot.tex
latexmk -pdf participant_guide_cursor.tex
```

To clean auxiliary files:

```bash
latexmk -c
```

## Related

- [Task Specification](../task/) - The PRD provided to participants
- [Grading Suite](../grader/) - How submissions are evaluated
