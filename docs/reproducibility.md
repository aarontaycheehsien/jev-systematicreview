# Reproducibility notes

## Exact saved-score evaluations

The scripts in `analysis/` recompute the released analyses from compact row-level score tables. They are deterministic, work offline, and make no Jev calls.

- `analysis/evaluate_dta.py` evaluates the eight CLEF-TAR DTA reviews after excluding rows without an abstract.
- `analysis/evaluate_donners.py` recomputes threshold performance for the Donners_2021 SYNERGY pilot.

Each results folder contains metric tables, a report, figures, and `evaluation_metadata.json`. Metadata records the input SHA-256, counts, calculation choices, software versions where applicable, and zero calls for that evaluation.

## DTA data and labels

The DTA score input has one row per review-record pair: 30,521 pairs, 30,497 distinct PMIDs, and 440 positive qrel labels before filtering. Repeated PMIDs across reviews are expected. Abstract availability is a Boolean derived from the cached PubMed abstract's non-null, non-empty status after whitespace trimming. The filtered set has 26,832 rows and 423 positive labels; 3,689 rows and 17 positive labels are excluded.

The positive label comes from the official CLEF-TAR 2019 DTA qrels and was used only after scoring. Source repository revisions and local source-file hashes are in `data/dta_source_manifest.json`. Criteria came from the pinned XITASO `lgar` source. PubMed metadata came from NCBI E-utilities. Titles and abstract text are not included in the repository.

## DTA ranking and metrics

For each review, sort by descending Jev probability; break ties using ascending numeric PMID and then PMID text. Ranks start at one.

- `WSS@95 = 1 - k95/N - 0.05`; k95 is the first rank at which cumulative positives reach `ceil(0.95 × R)`.
- `WSS@100 = 1 - k100/N`; k100 is the rank of the last positive.
- MAP is mean average precision across relevant records.
- Recall@5%, @10%, @20%, and @50% use the first `ceil(p × N)` ranked records, with at least one record.
- Fixed-threshold statistics use probability 0.50, carried forward from the earlier pilot. Oracle threshold metrics are post-hoc descriptions based on labels.
- Aggregate values are unweighted arithmetic means across the eight review-level values; standard deviations are sample SD.

The output `review_metrics.csv` contains the full set of review metrics. The compact score input is sufficient to reproduce them without abstracts.

## Donners_2021 pilot

The pilot score file provides one record per OpenAlex work identifier with its final inclusion label and Jev probability. The output script recalculates threshold confusion matrices from these saved values. Its 100%-recall threshold is chosen after examining labels and is not prospectively validated. The dataset has 258 records and 15 positives. The dataset citation is in `data/synergy-dataset-1.0/Donners_2021/CITATION.txt`; results are in `results/donners_2021/`.

## Recorded inference runs

The DTA scoring run recorded 30,521 successful Jev decisions, no API errors, and returned `jev-1.13.0`. The score file contains 33,373,017 input tokens and 610,420 output tokens. Summed call latency is not wall time because requests ran concurrently. At the price captured in the original summary, estimated input cost was $1.4017; provider billing is authoritative. The pilot scored 258 records. These are records of the original runs; offline re-evaluation made zero Jev calls.

## Fresh scoring provenance

`run_dta_benchmark.py` documents the prompt, criteria processing, official DTA topic/qrel source locations, PubMed retrieval, tie-breaking, and incremental call storage. `run_jev_screening.py` documents the pilot eligibility question and dataset retrieval. Running either in full can use external services and may incur cost. Fresh outputs may differ as models and source metadata change; released score tables are the source of truth for the packaged evaluations.

## Limitations and terms

Final review inclusion is not necessarily the original title/abstract screening decision. The filtered DTA analysis changes both denominators and positive counts. The pilot contains one review; the DTA analysis contains eight retrospective topics. Neither establishes safe autonomous screening or generalization. Published-system comparisons are contextual only because models, prompts, and ranking methods differ. No software or data license is asserted here; upstream sources retain their own terms.
