# Jev screening experiments

This repository packages two retrospective Jev screening experiments and their saved record-level predictions. The main analysis is an offline re-evaluation of Jev on the eight CLEF-TAR 2019 diagnostic test accuracy (DTA) reviews, restricted to records with non-missing abstracts. The earlier Donners_2021 SYNERGY pilot is also reproducible from saved scores.

Both evaluations can be rerun from the included compact score tables. The released row-level data contain identifiers, relevance labels, model probabilities, abstract-availability flags, and call usage metadata. They omit article titles and abstract text. **The evaluation scripts make no Jev calls and need no API key.**

## Reproduce the evaluations

Python 3.10 or newer is recommended. Install the small dependency set used by the offline evaluators:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install pandas matplotlib
```

Recreate the filtered DTA analysis and its tables and figures:

```powershell
.\.venv\Scripts\python.exe analysis\evaluate_dta.py
```

Recreate the Donners_2021 saved-score analysis:

```powershell
.\.venv\Scripts\python.exe analysis\evaluate_donners.py
```

DTA outputs go to `results/filtered_abstracts/`; pilot outputs go to `results/donners_2021/`. Each output folder includes an input SHA-256 in `evaluation_metadata.json`. Both evaluators accept `--input` and `--output-dir` overrides.

## Main result: DTA, non-missing abstracts

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

The filter excludes 3,689 of 30,521 review-record pairs and 17 positive labels. It leaves 26,832 records—two more than 26,830. A PMID appearing in more than one review counts once per review.

## Methods and sources

DTA scores are ranked within each review by descending Jev retain probability. Ties are ordered by ascending numeric PMID, then PMID text. WSS@95 is `1 - k95/N - 0.05`, where k95 is the first rank reaching at least 95% of the review's filtered positives. WSS@100 is `1 - rank_of_last_positive/N`. Aggregate means are unweighted arithmetic means across eight reviews.

Qrel labels are evaluation-only; they were not included in the Jev prompt or state. Abstract availability is a Boolean saved from PubMed metadata used in the original run. The evaluation does not download abstracts. See [`docs/reproducibility.md`](docs/reproducibility.md), [`data/README.md`](data/README.md), and the result reports for full metrics, source revisions, caveats, and data fields.

- Donners et al. (2021), *Pharmacokinetics and Associated Efficacy of Emicizumab in Humans: A Systematic Review*. [DOI: 10.1007/s40262-021-01042-w](https://doi.org/10.1007/s40262-021-01042-w).
- CLEF-TAR 2019 DTA topics and qrels, pinned revision: see [`data/dta_source_manifest.json`](data/dta_source_manifest.json).
- Review-specific criteria from XITASO/lgar, also pinned in that manifest.
- PubMed metadata for the original DTA scoring run came from [NCBI E-utilities](https://www.ncbi.nlm.nih.gov/books/NBK25501/). PMIDs are included to resolve records at source.

## Fresh scoring workflows

`run_jev_screening.py` and `run_dta_benchmark.py` preserve the original full scoring workflows. Running them makes external Jev calls; a full DTA run also retrieves PubMed metadata. Fresh scoring may incur provider charges and produce different predictions as models or source metadata change. It is not needed to reproduce the included saved-score evaluations.

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:TYPESAFE_API_KEY = "set-this-locally"
.\.venv\Scripts\python.exe run_jev_screening.py --full
.\.venv\Scripts\python.exe run_dta_benchmark.py --workers 8
```

The DTA runner downloads pinned topics, qrels, and criteria when absent. Never commit a real API key or the local PubMed response cache.

## Interpretation and limitations

The labels represent studies ultimately included in reviews, not necessarily decisions made during original title-and-abstract screening. The Donners_2021 pilot contains one review and 15 positives; the DTA benchmark contains eight retrospective topics. Neither experiment validates autonomous screening or establishes generalization. Filtering the DTA set changes both denominators and positive counts. Published-system comparisons are descriptive, not head-to-head; models, criteria representations, and ranking methods differ.

## Repository map

- `analysis/` — deterministic offline evaluation scripts.
- `data/jev_dta_scores.csv` — DTA predictions and labels for 30,521 pairs.
- `data/jev_donners2021_scores.csv` — Donners_2021 predictions and labels for 258 records.
- `data/*manifest.json` — source revisions, input hashes, counts, and fields.
- `data/README.md` — data dictionary, provenance, and source links.
- `results/` — regenerated text-free tables, reports, metadata, and figures.
- `run_dta_benchmark.py`, `run_jev_screening.py` — original scoring workflows; full runs may call Jev.
