# Filtered Jev evaluation: CLEF-TAR 2019 DTA reviews

Recomputed offline from `data/jev_dta_scores.csv`. **No Jev calls were made.** The input SHA-256 is `04232aacc47b2d4b52545721d77f0f8644ef210c85649bde72f405b04f8991c2`.

The source file contains 30,521 review-record rows and 440 positive labels. Excluding rows marked as having no non-empty abstract removes 3,689 rows and 17 positives. The filtered total is 26,832 rows (+2 versus 26,830), with 423 positives.

Records are ranked within review by descending Jev probability. Ties use ascending numeric PMID, then PMID text. `WSS@95 = 1 - k95/N - 0.05`, where k95 is the first rank reaching at least 95% of positives. `WSS@100 = 1 - rank of the last positive/N`. The aggregate is the unweighted arithmetic mean over eight reviews.

| Review | N | Positives | WSS@95 | WSS@100 |
|---|---:|---:|---:|---:|
| CD008874 | 1,799 | 114 | 0.760450 | 0.764314 |
| CD009044 | 3,120 | 11 | 0.781410 | 0.831410 |
| CD011686 | 8,032 | 63 | 0.753660 | 0.451942 |
| CD012080 | 6,314 | 73 | 0.800491 | 0.717928 |
| CD012233 | 430 | 38 | 0.273256 | 0.279070 |
| CD012567 | 5,863 | 11 | 0.931921 | 0.981921 |
| CD012669 | 1,155 | 70 | 0.588095 | 0.440693 |
| CD012768 | 119 | 43 | 0.294538 | 0.268908 |
| **Mean** | **26,832** | **423** | **0.647978** | **0.592023** |

`review_metrics.csv` includes WSS@95, WSS@100, MAP, recall at 5/10/20/50%, fixed-0.50 threshold metrics, and each review's relevant ranks. `ranked_scores_nonmissing_abstract.csv` preserves the ranked rows; `low_scoring_positives.csv` identifies positives after the WSS@95 cutoff or below the fixed 0.50 threshold. All files omit article text.

`published_comparison.csv` carries forward reported results for context. It is descriptive only: those systems use different criteria representations, models, and ranking procedures, and were not compared head-to-head on this filtered set.
