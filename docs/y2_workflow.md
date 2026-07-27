# Reviewed Y2 Transformation and Linked Master

The production workflow encodes the verified PSPP transformations in
`configs/ourboro/y2_transformations.json`. The original legacy syntax is not
executed or interpreted. Its repaired slices and the PSPP oracle are identified
by hash in `configs/ourboro/y2_provenance.json`.

Run the complete workflow with new output paths:

```bash
ourboro-pipeline build-y2-master \
  --input-csv FOLLOWUP.csv \
  --master-sav MASTER.sav \
  --crosswalk-xlsx CROSSWALK.xlsx \
  --oracle-sav followup_transformed_aligned.sav \
  --config configs/ourboro/y2_transformations.json \
  --output-dir outputs/y2-build
```

The command stops before linking if the Python-transformed SAV differs from the
reviewed PSPP oracle. Individual `transform-wave`, `validate-transform`, and
`build-linked-master` commands are available for diagnosis and partial reruns.

Expected real-data results are 1,635 transformed follow-up rows with 206
columns, followed by a linked master containing 9,551 rows and 992 columns.

Build the approved cluster assignment artifact after the linked master is built:

```bash
ourboro-pipeline build-cluster-assignments \
  --linked-master-csv outputs/y2-build/ourboro_master_linked_y2.csv \
  --config configs/ourboro/analysis_ready_export.json \
  --output-csv outputs/y2-build/cluster_assignments_labeled.csv \
  --report-json outputs/y2-build/cluster_assignments_labeled_report.json
```

The artifact contains `respondent_id`, stable `cluster_code`, and the original
SPSS `cluster_label`. Only original cluster codes 1-5 are included. Code 6
(`Ourboro clients`) and blank cluster assignments remain in the linked master
but are excluded from analysis; cluster assignments are never invented or
imputed.

Then produce the ANOVA handoff dataset:

```bash
ourboro-pipeline export-analysis-ready \
  --linked-master-csv outputs/y2-build/ourboro_master_linked_y2.csv \
  --clusters-csv outputs/y2-build/cluster_assignments_labeled.csv \
  --config configs/ourboro/analysis_ready_export.json \
  --output-csv outputs/y2-build/analysis_ready_long.csv \
  --report-json outputs/y2-build/analysis_ready_long_report.json
```

The export verifies every supplied code against the original linked-master
cluster source, then excludes respondents without approved assignments. Its JSON
report separates excluded-code, blank-source, and missing-artifact counts by row
and respondent. The current real-data baseline has 3,232 analysis-eligible
respondents before the cluster filter: 1,910 included in clusters 1-5, 74
excluded in cluster 6, and 1,248 excluded with blank original SPSS cluster
assignments. The labeled assignment artifact contains 5,287 master respondents.
The filtered long export contains 3,157 rows across 1,910 respondents (`Y0`: 458,
`Y1`: 1,633, `Y2`: 1,066).

The resulting long-format dataset contains `respondent_id`, `cluster_code`,
human-readable `cluster_label`, `wave`, and numeric DV columns for
`analysis-engine`. Numeric DVs are serialized with 14 significant digits so
artifact hashes remain stable across supported Python and NumPy runtimes.
