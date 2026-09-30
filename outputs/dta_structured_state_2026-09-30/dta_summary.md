# Jev on CLEF-TAR 2019 DTA reviews

## Dataset and validation

- Source set: official CLEF-TAR 2019 Task 2 Testing DTA PMID lists and `full.test.dta.abs.2019.qrels`; PubMed title/abstract metadata fetched with NCBI E-utilities and cached locally.
- Reviews: 8 requested topics. Candidate PMID and qrel sets matched exactly before scoring (30,521 review-record pairs, 30,497 distinct PMIDs, and 440 relevant qrel labels; per-review counts are in the result table).
- Criteria: review-specific inclusion/exclusion criteria, questions, objectives and title copied to `dta_criteria_used.json`.
- PubMed records not retrieved: 0; missing abstracts among processed review-record pairs: 3689 (3688 distinct PMIDs).
- Successful Jev scores: 30521; API failures: 0; returned model(s): jev-1.13.0.
- Gold qrels are evaluation-only and are not in the Jev state or question. No examples, tuning, or DTA label feedback were used.
- Ties are ordered deterministically by numeric PMID ascending after descending Jev retain probability.
- Recall@k uses the first `ceil(k × N)` records (minimum one). WSS@95 uses the first rank where cumulative positives reach at least 95% of the qrel positives, then `1 - rank/N - 0.05`. WSS@100 is `1 - last_relevant_rank/N`.

## Primary results

Mean WSS@95 was 0.631 (SD 0.259; median 0.672; range 0.171–0.926).

Aggregate metrics (arithmetic mean across review-level values; SD is sample standard deviation):

- WSS@95: 0.631 (SD 0.259; median 0.672; range 0.171–0.926)
- WSS@100: 0.585 (SD 0.309; median 0.605; range 0.168–0.976)
- MAP: 0.366 (SD 0.167; median 0.392; range 0.094–0.585)
- Recall@5%: 0.467 (SD 0.304; median 0.365; range 0.133–1.000)
- Recall@10%: 0.671 (SD 0.277; median 0.645; range 0.200–1.000)
- Recall@20%: 0.833 (SD 0.216; median 0.898; range 0.378–1.000)
- Recall@50%: 0.950 (SD 0.094; median 1.000; range 0.733–1.000)

### Per review

- CD008874: WSS@95 0.599; WSS@100 0.560; MAP 0.480; R@5/10/20/50 43.2%/61.9%/81.4%/100.0%; n=2382, relevant=118
- CD009044: WSS@95 0.879; WSS@100 0.929; MAP 0.502; R@5/10/20/50 81.8%/100.0%/100.0%/100.0%; n=3169, relevant=11
- CD011686: WSS@95 0.745; WSS@100 0.650; MAP 0.094; R@5/10/20/50 29.7%/67.2%/93.8%/100.0%; n=9729, relevant=64
- CD012080: WSS@95 0.790; WSS@100 0.802; MAP 0.176; R@5/10/20/50 54.5%/87.0%/100.0%/100.0%; n=6643, relevant=77
- CD012233: WSS@95 0.374; WSS@100 0.242; MAP 0.393; R@5/10/20/50 25.6%/48.8%/67.4%/90.7%; n=472, relevant=43
- CD012567: WSS@95 0.926; WSS@100 0.976; MAP 0.391; R@5/10/20/50 100.0%/100.0%/100.0%/100.0%; n=6735, relevant=11
- CD012669: WSS@95 0.563; WSS@100 0.352; MAP 0.303; R@5/10/20/50 25.4%/52.1%/85.9%/95.8%; n=1260, relevant=71
- CD012768: WSS@95 0.171; WSS@100 0.168; MAP 0.585; R@5/10/20/50 13.3%/20.0%/37.8%/73.3%; n=131, relevant=45

## Published comparison

Jev's mean differs from 2024's 0.653 by -0.022 and from 2026 Soft-Vote's 0.680 by -0.049. These are descriptive comparisons, not head-to-head tests. Performance was lowest on CD012768 (WSS@95 0.171) and highest on CD012567 (WSS@95 0.926).

| System | Setting | Mean DTA WSS@95 (SD) | Mean DTA WSS@100 (SD) |
|---|---|---:|---:|
| Akinseloyin 2024, Claude 3 QA + Gemini embedding reranking | zero-shot | 0.653 (not reported) | 0.573 (not reported) |
| Akinseloyin 2026, Soft-Vote | zero-shot multi-LLM | 0.680 (0.228) | 0.667 (0.266) |
| Jev | zero-shot single judgement model | 0.631 (0.259) | 0.585 (0.309) |

The comparison is not head-to-head. The [2024 system](https://academic.oup.com/jamia/article/31/9/1939/7718667) converted criteria into question-answering tasks and re-ranked with embeddings; the [2026 Soft-Vote system](https://academic.oup.com/biomethods/article/11/1/bpag006/8460762) combines multiple LLM outputs; Jev uses one bounded judgment per record without review-specific training. Differences in model, prompt construction, ranking and implementation matter, so screening performance should be considered alongside model and computational complexity.

## Carried-forward fixed threshold (secondary)

Threshold 0.50 is carried forward from the earlier Jev experiment without using DTA labels to alter it. Per-review recall and workload reduction are in `dta_review_results.csv`. This threshold was not prospectively validated as universal. Any `post_hoc_oracle_100_threshold` values in that file are label-informed descriptions only.

Across the eight reviews, fixed-threshold recall averaged 71.4% (range 9.4%–91.5%) and workload reduction averaged 81.7%. The wide recall range shows that the earlier probability threshold does not transfer consistently across these criteria sets.

## Difficult relevant records

`dta_low_scoring_included.csv` lists every relevant record below the rank needed for 95% recall or below the carried-forward 0.50 threshold. The criteria field supplies review eligibility language for manual inspection; it does not assert why Jev scored a record poorly. Missing eligibility characteristics in abstracts should be assessed from the records themselves.

## Runtime and API use

- Total input tokens: 34,760,608; output tokens: 610,420.
- Approximate Jev inference cost: $1.4599, calculated at $0.042 per million input tokens for Jev 1.13 ([price checked 2026-09-21](https://www.typesafeai.org/guides/jev-pricing)); output tokens are free. Provider account billing is authoritative.
- Final resumed scoring segment: about 8.3 minutes; time for the earlier partial segment was not recorded.
- Sum of recorded call latencies: 9108.2 seconds across concurrent requests (not wall time).

## Interpretation

Mean WSS@95 was 0.631 (SD 0.259; median 0.672; range 0.171–0.926). Jev's mean differs from 2024's 0.653 by -0.022 and from 2026 Soft-Vote's 0.680 by -0.049. These are descriptive comparisons, not head-to-head tests. Performance was lowest on CD012768 (WSS@95 0.171) and highest on CD012567 (WSS@95 0.926). These eight retrospective DTA topics do not establish that Jev is safe for autonomous review screening or that results generalize to other review types. CLEF qrels define this benchmark's relevance labels; they are used only after scoring to evaluate the fixed ranking.
