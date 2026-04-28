# Pipeline protocol

End-to-end flow from a participant's submission zip to one row in
the aggregated dataset CSV. This document covers the submission
contract participants follow, the researcher-side processing
sequence, the on-disk artifact layout under one output root, the
manifest schema that audits every operation, and the dataset CSV
column schema.

For per-stage script usage and the configuration file shape, see
[README.md](README.md).

## Submission contract

A participant produces one zip file at the end of each case-study
session. The filename and inner layout are strict; the validate
stage rejects anything that does not match.

### Filename

```
{PID}_S{1|2}_{apm|speckit}.zip
```

Three segments separated by underscores:

- `PID` matches `P\d{3}` (the participant identifier; uppercase in
  the canonical form).
- `S1` or `S2` (the participant's first or second case-study
  session).
- `apm` or `speckit` (the framework the participant used in this
  session; `speckit` is one word with no hyphen, matching the
  parser's `--framework` flag).

The same three-segment string without the `.zip` suffix is the
**manifest key** for the submission, and it names the per-submission
directories under both `_staging/` and the per-participant tree.

### Inner layout

```
P001_S1_apm/
├── solution.patch
└── transcripts/
    ├── <sessionId>.jsonl
    ├── <sessionId>.jsonl
    └── ...
```

Two top-level entries inside the zip's named directory:

- `solution.patch`: the patch the participant produced against the
  pinned baseline. Consumed by the grader.
- `transcripts/`: a flat directory of one or more
  `<sessionId>.jsonl` files copied straight from
  `~/.claude/projects/<dashed-cwd>/`. Filenames stay as the UUIDs
  Claude Code wrote them with. Consumed by the parser.

The participant guide instructs participants to omit the
per-session `<sessionId>/subagents/` and `<sessionId>/tool-results/`
subdirectories Claude Code writes alongside the JSONL files; the
validate stage rejects nested files or directories under
`transcripts/` to keep the dataset clean of artifacts the parser
does not consume.

## Processing sequence

The researcher receives a submission zip and runs the five stages
in order. Each stage records its outcome in the manifest under
`<output-root>/pipeline_manifest.json`; a stage that fails leaves
no manifest entry and the chain stops.

```
zip ──► validate ──► grade ──► parse ──► combine ──► add_to_dataset
                                                          │
                                                          ▼
                                                    dataset.csv row
```

1. **validate** unpacks the zip into the staging area and confirms
   the layout.
2. **grade** subprocesses `python -m grader` against the staged
   patch, the configured eclass checkout, and the testing-
   environment install; the grader's results JSON is promoted to
   the per-participant directory.
3. **parse** subprocesses `cc_chat_parser` against the staged
   transcripts directory; the canonical metrics artifact is
   promoted alongside sealed sidecar copies of the raw transcripts.
4. **combine** wraps the grader and parser outputs into one
   per-submission combined artifact.
5. **add_to_dataset** appends one flat row to the aggregated
   dataset CSV.

After a successful run, the operator can invoke `pipeline.cleanup
<manifest_key> --output-root <root>` to remove the staging copy.
The manifest entry survives the cleanup so the audit trail is
preserved.

## Output layout under one output root

The output root carries everything the pipeline produces for one
study population: the manifest, the aggregated dataset CSV, an
ephemeral staging area, and one directory per submission with
promoted artifacts.

```
<output-root>/
├── pipeline_manifest.json
├── dataset.csv
├── pipeline.yaml                 # optional default-paths config
├── _staging/
│   ├── P001_S1_apm/
│   │   ├── solution.patch
│   │   └── transcripts/
│   │       └── <sessionId>.jsonl
│   └── P001_S2_speckit/
│       └── ...
└── P001/
    ├── S1_apm/
    │   ├── results.json
    │   ├── metrics.json
    │   ├── combined.json
    │   └── sanitized_transcripts/
    │       └── sanitized_<sessionId>.json
    └── S2_speckit/
        └── ...
```

The dataset directory has no opinion on where it lives; it can be
a clone of `bsc-apm-case-study-data/`, a working directory, or a
tmpfs for testing. Every pipeline stage takes `--output-root` as
the only required path; the configurable grader, eclass, parser,
and mock roots are referenced only by the stages that need them.

## Manifest schema

The manifest at `<output-root>/pipeline_manifest.json` is the audit
trail. One top-level entry per submission keyed by manifest key;
each entry carries one block per stage with the stage's status,
timestamp, input and output paths, checksums, and stage-specific
fields.

```json
{
  "created_at": "...",
  "updated_at": "...",
  "entries": {
    "P001_S1_apm": {
      "validate": {
        "timestamp": "...",
        "status": "success",
        "input_zip": "P001_S1_apm.zip",
        "input_checksum": "sha256:...",
        "staging_path": "_staging/P001_S1_apm",
        "transcripts_count": 3,
        "warnings": []
      },
      "grade": {
        "timestamp": "...",
        "status": "success",
        "input_patch": "solution.patch",
        "input_checksum": "sha256:...",
        "output_results": "P001/S1_apm/results.json",
        "output_checksum": "sha256:...",
        "score": "87/100",
        "score_breakdown": {
          "python_baseline": "12/12",
          "python_feature": "31/36",
          "c_replica": "44/52"
        }
      },
      "parse": {
        "timestamp": "...",
        "status": "success",
        "framework": "apm",
        "input_transcripts_count": 3,
        "output_metrics": "P001/S1_apm/metrics.json",
        "output_checksum": "sha256:...",
        "sanitized_files": ["sanitized_<id>.json", "..."]
      },
      "combine": {
        "timestamp": "...",
        "status": "success",
        "input_files": ["results.json", "metrics.json"],
        "output_combined": "P001/S1_apm/combined.json",
        "output_checksum": "sha256:..."
      },
      "add_to_dataset": {
        "timestamp": "...",
        "status": "success",
        "input_combined": "combined.json",
        "input_checksum": "sha256:...",
        "output_file": "dataset.csv",
        "dataset_row_number": 12,
        "dataset_checksum_before": "sha256:...",
        "dataset_checksum_after": "sha256:..."
      }
    }
  }
}
```

Stage names: `validate`, `grade`, `parse`, `combine`,
`add_to_dataset`. Status values: `success`, `warning`, `error`. The
manifest uses fcntl-based locking and atomic-write semantics so
concurrent operators serialise on writes and concurrent readers
never see a partial write.

## Combined artifact schema

The per-submission `combined.json` wraps grader and parser outputs
with submission identifiers:

```json
{
  "participant_id": "P001",
  "session": "S1",
  "framework": "apm",
  "processing_timestamp": "...",
  "grading": {
    "total":           {"score": 87, "max": 100},
    "python_baseline": {"score": 12, "max": 12},
    "python_feature":  {"score": 31, "max": 36},
    "c_replica":       {"score": 44, "max": 52}
  },
  "metrics": "<the entire cc_chat_parser metrics artifact, unmodified>"
}
```

The `metrics` block is the parser's scope-nested artifact verbatim;
downstream analyses reach into `metrics.session.economic.cost_usd.value`
and similar without the pipeline re-deriving anything.

## Dataset CSV schema

`dataset.csv` carries one row per submission with session-scope
measurements only. Phase-scope and role-scope decompositions stay in
`combined.json` for analyses that want them. Bucket-share dicts are
flattened into per-bucket columns so downstream statistics software
does not have to parse JSON inside a CSV cell.

Column families, in order:

- **Identifiers** (4): `participant_id`, `session`, `framework`,
  `processing_timestamp`.
- **Session metadata** (8): `cc_version`, `model`, `model_drift`,
  `entrypoint`, `auth_mode_indicator`, `service_tier`,
  `session_start_timestamp`, `session_end_timestamp`.
- **Grading** (5): `total_score`, `max_score`,
  `python_baseline_score`, `python_feature_score`,
  `c_replica_score`.
- **Economic, session scope** (11): `cost_usd`,
  `total_input_tokens`, `total_output_tokens`,
  `total_cache_read_tokens`, `total_cache_5m_tokens`,
  `total_cache_1h_tokens`, `total_prompt_tokens`,
  `main_input_tokens`, `main_output_tokens`,
  `delegated_input_tokens`, `delegated_output_tokens`.
- **Time, session scope** (10): `duration`, `turn_time`,
  `turn_time_solo`, `turn_time_concurrent`, `inter_turn_time`,
  `turn_count`, `mean_turn_duration`, `turn_duration_p50`,
  `turn_duration_p95`, `turn_duration_stdev`.
- **User input, session scope** (10): `turn_prompt_count`,
  `steer_delivered_count`, `steer_abandoned_count`,
  `steer_attempted_count`, `turn_prompts_share_protocol`,
  `turn_prompts_share_short`, `turn_prompts_share_standard`,
  `all_inputs_share_protocol`, `all_inputs_share_short`,
  `all_inputs_share_standard`.
- **Reliability** (1): `tool_success_rate`.
- **Supplementary** (3): `subagent_count`, `subagent_tool_count`,
  `reasoning_token_share`.
- **Diagnostics** (7): `compaction_events_total`,
  `cost_excludes_compaction_synthesis`,
  `synthetic_assistant_records_excluded`,
  `agent_dispatches_without_usage`, `entrypoint_valid`,
  `auth_mode_valid`, `invariant_failures`.

Total: 59 columns. The canonical column list and order is defined
in `pipeline/add_to_dataset.py`.

`invariant_failures` is the count of failed invariant checks in
the parser's diagnostics block; the names of the failed checks
live in `combined.json.metrics.diagnostics.invariant_checks`.

## Failure recovery

Each stage is idempotent against its inputs: re-running a stage
overwrites its prior output and re-records its manifest entry. The
chain stops on the first stage that fails; the operator fixes the
underlying issue and re-runs from that stage. The orchestrator
(`pipeline.run`) does not retry; manual re-runs are the recovery
path.

Common recovery scenarios:

- **Testing environment down**: run `<mock-root>/scripts/up`
  and re-run `pipeline.grade`.
- **Parser version bump**: re-run `pipeline.parse` to refresh
  `metrics.json`, then re-run `combine` and `add_to_dataset`.
- **Edited combined artifact**: `validate_dataset` warns about
  the checksum mismatch; the operator either accepts the edit
  (the dataset row is what was added at the time it was added)
  or restores the previous content from a backup.

## Related

- [README.md](README.md): per-stage script usage and CLI flags.
- [../parser/README.md](../parser/README.md): the parser package
  the parse stage subprocesses.
- [../grader/README.md](../grader/README.md): the grader the
  grade stage subprocesses.
