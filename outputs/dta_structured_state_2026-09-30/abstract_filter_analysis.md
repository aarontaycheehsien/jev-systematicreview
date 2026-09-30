# DTA rerun: full set and abstract-available subset

## Run and filter

- Successful scores: 30,521/30,521; errors: 0.
- Returned model: jev-1.13.0.
- Abstract filter: excludes blank/missing abstracts (title availability was 30,521/30,521); 3,689 review-record pairs and 3,688 unique PMIDs excluded.

The full analysis ranks all 30,521 review-record pairs, including records without abstracts. The filtered analysis ranks only pairs with a non-blank abstract. All titles are available, so requiring both title and abstract gives the same filtered set. Metrics are unweighted means of the eight review-level values; SD is the sample SD. WSS@95 is `1 - k95/N - 0.05`, where `k95` is the first rank to reach at least 95% recall.

## Aggregate results

| Metric | All records, mean (SD) | Abstract available, mean (SD) | Filtered minus all |
|---|---:|---:|---:|
| WSS@95 | 0.631 (0.259) | 0.661 (0.291) | +0.031 |
| WSS@100 | 0.585 (0.309) | 0.636 (0.313) | +0.051 |
| MAP | 0.366 (0.167) | 0.457 (0.174) | +0.091 |
| Recall@5% | 0.467 (0.304) | 0.577 (0.326) | +0.110 |
| Recall@10% | 0.671 (0.277) | 0.733 (0.280) | +0.062 |
| Recall@20% | 0.833 (0.216) | 0.867 (0.210) | +0.034 |
| Recall@50% | 0.950 (0.094) | 0.953 (0.089) | +0.003 |
| Fixed 0.50 recall | 0.714 (0.274) | 0.706 (0.279) | -0.007 |
| Fixed 0.50 workload reduction | 0.817 (0.241) | 0.839 (0.235) | +0.021 |

## Per-review ranking performance

N and positive counts are shown as `N (positives)`.

| Review | All: N (positive) | Filtered: N (positive) | WSS@95 all | WSS@95 filtered | Δ WSS@95 | WSS@100 all | WSS@100 filtered |
|---|---:|---:|---:|---:|---:|---:|---:|
| CD008874 | 2,382 (118) | 1,799 (114) | 0.599 | 0.749 | +0.151 | 0.560 | 0.724 |
| CD009044 | 3,169 (11) | 3,120 (11) | 0.879 | 0.889 | +0.010 | 0.929 | 0.939 |
| CD011686 | 9,729 (64) | 8,032 (63) | 0.745 | 0.863 | +0.119 | 0.650 | 0.780 |
| CD012080 | 6,643 (77) | 6,314 (73) | 0.790 | 0.814 | +0.024 | 0.802 | 0.830 |
| CD012233 | 472 (43) | 430 (38) | 0.374 | 0.248 | -0.126 | 0.242 | 0.265 |
| CD012567 | 6,735 (11) | 5,863 (11) | 0.926 | 0.937 | +0.011 | 0.976 | 0.987 |
| CD012669 | 1,260 (71) | 1,155 (70) | 0.563 | 0.598 | +0.034 | 0.352 | 0.379 |
| CD012768 | 131 (45) | 119 (43) | 0.171 | 0.194 | +0.022 | 0.168 | 0.185 |
| **Mean** | **30,521 (440)** | **26,832 (423)** | **0.631** | **0.661** | **+0.031** | **0.585** | **0.636** |

## Comparison with the previous request

The earlier run scored the same full set with Jev `jev-1.13.0`. Under the previous request, mean WSS@95 was 0.616 on all records and 0.648 on the abstract-available subset; this rerun scores 0.631 and 0.661, respectively. These are descriptive changes after moving the review rubric into Noul instructions and the record text into structured `state`; they do not isolate the effect of JSON formatting alone.

Filtering raises the mean ranking metrics, but it also removes 17 of the 440 qrel-positive pairs (17/440 = 3.9%). That is a change in evaluation population, not evidence that Jev improved on those records. On the full set, CD012768 and CD012233 have the lowest WSS@95 (0.171 and 0.374); in the filtered set, the same reviews remain lowest (0.194 and 0.248). Treat the fixed 0.50 threshold descriptively; it is not prospectively validated.
