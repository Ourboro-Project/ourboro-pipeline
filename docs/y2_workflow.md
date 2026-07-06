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

To produce the ANOVA handoff dataset after the linked master is built:

```bash
ourboro-pipeline export-analysis-ready \
  --linked-master-csv outputs/y2-build/ourboro_master_linked_y2.csv \
  --clusters-csv CLUSTERS.csv \
  --config configs/ourboro/analysis_ready_export.json \
  --output-csv outputs/y2-build/analysis_ready_long.csv \
  --report-json outputs/y2-build/analysis_ready_long_report.json
```

This export writes the long-format analysis dataset consumed by `analysis-engine`.
