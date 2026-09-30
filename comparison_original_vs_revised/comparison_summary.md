# Original vs revised Jev screening comparison

## Paired scores

- Successfully matched records: 258 (original successful: 258; revised successful: 258)
- Model returned, original: jev-1.13.0
- Model returned, revised: jev-1.13.0
- Mean Jev probability, original: 0.4022
- Mean Jev probability, revised: 0.4324
- Median Jev probability, original: 0.3400
- Median Jev probability, revised: 0.3800
- Mean absolute change: 0.0808
- Median absolute change: 0.0500
- Maximum absolute change: 0.5300
- Pearson correlation: 0.9197
- Spearman rank correlation: 0.9158

### Absolute probability change

| Absolute change | Records | Percentage |
|---|---:|---:|
| <0.01 | 23 | 8.9% |
| 0.01–<0.05 | 107 | 41.5% |
| 0.05–<0.10 | 51 | 19.8% |
| ≥0.10 | 77 | 29.8% |

## Screening performance

Fixed-threshold figures use the same evaluation logic as the original runner: retain when probability ≥ threshold, thresholds 0.1 through 0.9, with recall, specificity, precision, and workload reduction reported in `threshold_comparison.csv`.

The 100%-recall oracle threshold is computed separately for each run as the minimum probability among ultimately included records. It uses the known final inclusion labels and is descriptive post-hoc analysis. Fixed-threshold and oracle results are retrospective; none is prospective performance or a validated operational threshold.

### At fixed threshold 0.50

| Run | Recall | Specificity | Precision | Workload reduction |
|---|---:|---:|---:|---:|
| Original | 80.0% | 73.7% | 15.8% | 70.5% |
| Revised | 86.7% | 64.2% | 13.0% | 61.2% |

### Post-hoc/oracle 100%-recall threshold

| Run | Threshold | Recall | Specificity | Precision | Workload reduction |
|---|---:|---:|---:|---:|---:|
| Original | 0.3300 | 100.0% | 51.0% | 11.2% | 48.1% |
| Revised | 0.3600 | 100.0% | 48.6% | 10.7% | 45.7% |

## Run comparability

- Original rows: 258 successful scores; revised rows: 258 successful scores.
- Token totals, original input/output: 266273 / 5160; revised: 267820 / 5160.
- Unresolved recorded failures, original: 0; revised: 0.
- Four initial revised-run API attempts for one missing-title record returned 400 (NaN/infinity); normalizing the title to an empty string fixed the structured-state serialization, and a retry succeeded. Failed attempts returned no usage values, so reported revised token totals include successful responses only.
- Probability changes describe sensitivity to request organization. They do not by themselves establish a better or worse screening result.
