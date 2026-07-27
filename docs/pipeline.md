# Ourboro Survey Pipeline

Internal Python tooling for reviewing, transforming, linking, and preparing
Ourboro/OIS survey data.

Current production scope is the reviewed Y2 follow-up rebuild. The pipeline
replaces a manually repaired PSPP workflow with reproducible Python code,
validates transformed data against a reviewed PSPP oracle, links Y2 into the
master dataset, and creates a labeled long-format handoff for statistical
analysis.

## Workflow

```text
raw Y2 follow-up CSV
  -> reviewed JSON transformation rules
  -> transformed Y2 CSV/SAV
  -> validation against reviewed PSPP oracle SAV
  -> linked master CSV/SAV
  -> labeled cluster assignments
  -> analysis-ready long CSV
  -> analysis-engine adapter
```

PSPP is a reviewed validation oracle, not the production runtime. Production
transformations are implemented in Python and controlled by reviewed JSON
configuration.

## Requirements

- Python 3.9 or newer
- Project-local virtual environment
- Runtime dependencies declared in `pyproject.toml`
- Reviewed source survey files supplied outside this repository

Create the environment from the repository root:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
```

Do not install project packages globally.

## Quick Start

### 1. Build the linked Y2 master

Use new output paths. Never write over source survey files.

```bash
.venv/bin/ourboro-pipeline build-y2-master \
  --input-csv FOLLOWUP.csv \
  --master-sav MASTER.sav \
  --crosswalk-xlsx CROSSWALK.xlsx \
  --oracle-sav followup_transformed_aligned.sav \
  --config configs/ourboro/y2_transformations.json \
  --output-dir outputs/y2-build
```

This command:

1. Transforms the raw follow-up CSV into aligned CSV and SAV files.
2. Compares the transformed SAV with the reviewed PSPP oracle.
3. Stops before linking if oracle validation fails.
4. Links deduplicated Y2 responses into the existing master.
5. Appends respondents who appear only in Y2.

Primary outputs:

```text
followup_transformed_y2.csv
followup_transformed_y2.sav
followup_transform_report.json
followup_oracle_validation.json
ourboro_master_linked_y2.csv
ourboro_master_linked_y2.sav
ourboro_master_linked_y2_report.json
```

### 2. Build labeled cluster assignments

```bash
.venv/bin/ourboro-pipeline build-cluster-assignments \
  --linked-master-csv outputs/y2-build/ourboro_master_linked_y2.csv \
  --config configs/ourboro/analysis_ready_export.json \
  --output-csv outputs/y2-build/cluster_assignments_labeled.csv \
  --report-json outputs/y2-build/cluster_assignments_labeled_report.json
```

Output schema:

```csv
respondent_id,cluster_code,cluster_label
```

Cluster assignments come only from the original linked-master SPSS cluster
field. The command does not infer or impute clusters.

### 3. Export the analysis-ready panel

```bash
.venv/bin/ourboro-pipeline export-analysis-ready \
  --linked-master-csv outputs/y2-build/ourboro_master_linked_y2.csv \
  --clusters-csv outputs/y2-build/cluster_assignments_labeled.csv \
  --config configs/ourboro/analysis_ready_export.json \
  --output-csv outputs/y2-build/analysis_ready_long.csv \
  --report-json outputs/y2-build/analysis_ready_long_report.json
```

Output schema:

```text
respondent_id, cluster_code, cluster_label, wave, <numeric DV columns...>
```

The exporter detects numeric fields under configured wave prefixes and writes
one row per eligible respondent-wave. Numeric values use 14 significant digits
so output hashes remain stable across supported Python and NumPy runtimes.

## Cluster Contract

Ourboro-specific cluster meaning belongs in the pipeline. Downstream analysis
code should remain generic and use the supplied labels.

| Code | Label | Analysis status |
| --- | --- | --- |
| 1 | Looked in the past but no longer planning | Included |
| 2 | Looking and planning | Included |
| 3 | Planning to buy not yet seriously looking | Included |
| 4 | Not looking will buy eventually | Included |
| 5 | Not looking not planning | Included |
| 6 | Ourboro clients | Excluded |

Blank original cluster assignments are also excluded. Excluded respondents
remain in the linked master and can be audited there.

Respondent IDs are selected in configured priority order. Current defaults are:

```text
PSIDBrokerID
ResponseId
Y0_ResponseId
Y1_ResponseId
Y2_ResponseId
```

The cluster report records how many included assignments came from each ID
source. The export also verifies every supplied cluster code and label against
the linked-master source and approved config before writing analysis data.

## Audit Reports

Every production command writes a JSON report containing input hashes, output
hashes, configured behavior, and record counts.

The analysis-ready report separates exclusions into:

- blank original cluster source
- configured excluded cluster code
- included source code missing from the supplied assignment artifact

This distinction prevents code 6, blank assignments, and incomplete artifacts
from being silently combined into one unexplained count.

## Validated Y2 Baseline

Current reviewed real-data baseline:

```text
Raw Y2 responses:                         1,635
Deduplicated Y2 responses:                1,627
Linked master rows:                       9,551
Linked master columns:                      992
Included cluster assignments:             5,287
Analysis-eligible respondents:             3,232
Included cluster 1-5 respondents:          1,910
Excluded cluster 6 respondents:               74
Excluded blank-cluster respondents:        1,248
Analysis-ready rows:                       3,157
Analysis-ready numeric DV columns:           192
```

Analysis-ready wave rows:

```text
Y0:   458
Y1: 1,633
Y2: 1,066
```

Final cluster and analysis exports were verified byte-for-byte across local
Python 3.12/NumPy 2.5 and server Python 3.9/NumPy 2.0 environments.

## Command Reference

List all commands and command-specific options:

```bash
.venv/bin/ourboro-pipeline --help
.venv/bin/ourboro-pipeline COMMAND --help
```

Current commands:

| Command | Responsibility |
| --- | --- |
| `build-review-bundle` | Build source-review artifacts |
| `extract-spss-metadata` | Extract metadata from SPSS syntax |
| `mapping-review` | Build mapping review output |
| `compare-columns` | Compare survey column sets |
| `rough-merge-followup` | Run the earlier rough CSV merge workflow |
| `transform-wave` | Apply reviewed transformation config to one wave |
| `validate-transform` | Compare a transformed SAV with its oracle |
| `build-linked-master` | Link a transformed follow-up wave into master |
| `build-y2-master` | Run transform, validation, and linking together |
| `build-cluster-assignments` | Build approved labeled cluster assignments |
| `export-analysis-ready` | Write long-format statistical handoff data |

Review and rough-merge commands support discovery and historical workflows.
The reviewed Y2 production path starts with `transform-wave` or
`build-y2-master`.

## Repository Layout

```text
configs/ourboro/
  y2_provenance.json
  y2_transformations.json
  analysis_ready_export.json

docs/
  pipeline.md
  y2_workflow.md

src/ourboro_pipeline/
  cli.py
  transform.py
  linked.py
  analysis_ready.py
  columns.py
  files.py
  merge.py
  review.py
  spss.py

tests/
  test_*.py
```

Key responsibilities:

- `transform.py`: reviewed transformations and oracle comparison
- `linked.py`: crosswalk-based Y2 deduplication and master linking
- `analysis_ready.py`: cluster generation, source validation, and long export
- `cli.py`: command-line entry points
- `configs/ourboro/`: reviewed behavior and provenance

## Verification

Run the full test suite:

```bash
.venv/bin/python -m pytest -q
```

Current baseline is 79 passing tests.

Run focused Y2 and handoff tests:

```bash
.venv/bin/python -m pytest -q \
  tests/test_transform.py \
  tests/test_linked.py \
  tests/test_analysis_ready.py
```

Before committing:

```bash
git status --short --branch
git diff
.venv/bin/python -m pytest -q
```

Stage exact paths only. Do not use `git add .` around raw or generated survey
artifacts.

## Data Safety

- Never modify original CSV, SAV, SPS, XLSX, or DOCX survey inputs.
- Write every generated artifact to a new output path.
- Do not commit raw survey data or generated CSV/SAV outputs.
- Keep credentials, private respondent data, virtual environments, caches, and
  operating-system metadata out of Git.
- Treat reports and respondent-level exports as private project data.

## Analysis Handoff

`analysis_ready_long.csv` is the pipeline-side contract for the downstream
`analysis-engine`. The engine still needs a production adapter that accepts this
long format and applies approved missing-wave policy before longitudinal tests.
Do not treat exploratory engine demo output as confirmatory research results.

See [`y2_workflow.md`](y2_workflow.md) for the shorter operator workflow.
