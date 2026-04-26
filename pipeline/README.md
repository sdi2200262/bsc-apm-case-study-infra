# Pipeline

Five-stage data-processing pipeline for participant submissions.
Turns one zipped submission into one row in the aggregated dataset,
with per-submission durable artifacts and a manifest audit trail
along the way.

For the submission contract, processing sequence, output layout,
manifest schema, and dataset CSV column schema, see
[PIPELINE.md](PIPELINE.md). This README covers per-script CLI
usage only.

## Modules

| Module | Role |
|---|---|
| `pipeline.validate` | Confirm a submission zip matches the contract; unpack to the staging area. |
| `pipeline.grade` | Apply the patch and run the grader; promote the results JSON. |
| `pipeline.parse` | Run the parser on the transcripts; promote the metrics JSON and sealed sidecars. |
| `pipeline.combine` | Wrap grader and parser outputs into one combined artifact. |
| `pipeline.add_to_dataset` | Append one flat row to the aggregated dataset CSV. |
| `pipeline.run` | Chain the five stages on one zip; halt on first non-zero exit. |
| `pipeline.validate_dataset` | Cross-check manifest entries against dataset rows for one output root. |
| `pipeline.inspect` | Render one submission's manifest history (text or JSON). |
| `pipeline.cleanup` | Remove a submission's staging copy after every stage has succeeded. |

## Prerequisites

- Python 3.10+ with `pyyaml`.
- A clone of the parser at a known path
  (`--parser-root`).
- A clone of the grader and the `eclass-mcp-server` source at known
  paths (`--grader-root`, `--eclass-root`); the openeclass Docker
  stack must be running before the grade stage executes.
- `CC_PARSER_SECRET` set in the environment for the parse stage's
  sanitisation pass.

## Common flags

Every stage takes:

- `--output-root <path>` (required): the dataset output root.
- `--config <path>` (optional): override the default
  `<output-root>/pipeline.yaml`.

`pipeline.yaml` lives at the dataset root and declares default
external paths so they need not be repeated on every invocation:

```yaml
paths:
  grader_root: /path/to/bsc-apm-case-study-task/grader
  eclass_root: /path/to/eclass-mcp-server
  parser_root: /path/to/bsc-apm-case-study-task/parser
```

CLI flags always win over the YAML.

## Quick start

```bash
# One-shot orchestrated run on a single submission
python -m pipeline.run P001_S1_apm.zip \
    --output-root /path/to/dataset \
    --grader-root /path/to/grader \
    --eclass-root /path/to/eclass-mcp-server \
    --parser-root /path/to/parser

# Or stage by stage (assuming pipeline.yaml supplies the paths)
python -m pipeline.validate       P001_S1_apm.zip --output-root /path/to/dataset
python -m pipeline.grade          P001_S1_apm     --output-root /path/to/dataset
python -m pipeline.parse          P001_S1_apm     --output-root /path/to/dataset
python -m pipeline.combine        P001_S1_apm     --output-root /path/to/dataset
python -m pipeline.add_to_dataset P001_S1_apm     --output-root /path/to/dataset

# Cross-check the dataset for one output root
python -m pipeline.validate_dataset --output-root /path/to/dataset

# Render one submission's manifest history (text or --json)
python -m pipeline.inspect P001_S1_apm --output-root /path/to/dataset
python -m pipeline.inspect P001_S1_apm --output-root /path/to/dataset --json

# Remove a submission's staging copy (only when all 5 stages succeeded)
python -m pipeline.cleanup P001_S1_apm --output-root /path/to/dataset
```

Each script's `--help` lists its complete flag set. See
[PIPELINE.md](PIPELINE.md) for the protocol and schemas the
scripts implement.

## Related

- [PIPELINE.md](PIPELINE.md): submission contract, processing
  sequence, output layout, manifest schema, dataset CSV columns,
  failure recovery.
- [../parser/README.md](../parser/README.md): the transcript
  parser the parse stage subprocesses.
- [../grader/README.md](../grader/README.md): the grader the
  grade stage subprocesses.
