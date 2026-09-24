# Data notes

## `jev_dta_scores.csv`

One row per 30,521 CLEF-TAR DTA review-record pairs. It omits article titles and abstracts.

| Column | Meaning |
|---|---|
| `review_id` | CLEF-TAR 2019 DTA review/topic identifier. |
| `pmid` | PubMed identifier, stored as text. |
| `label_included` | Binary relevance label derived from the official abstract-level qrels; evaluation-only. |
| `jev_probability` | Saved Jev probability of retaining the record for human screening. |
| `jev_model` | Model version returned by Jev. |
| `abstract_available` | True when the cached PubMed abstract was non-null and non-empty after trimming whitespace. |
| `input_tokens` | Jev call input token count. |
| `output_tokens` | Jev call output token count. |
| `latency_seconds` | Recorded call latency. |

There are 30,497 distinct PMIDs and 440 positive review-record labels before filtering. Repeated PMIDs across reviews are expected. The abstract-available subset has 26,832 rows and 423 positives.

## `jev_donners2021_scores.csv`

One row per 258 scored OpenAlex work identifiers in the Donners_2021 SYNERGY pilot. It contains the final inclusion label, saved Jev score, model and call usage fields, and an abstract-availability Boolean. It omits work titles and abstract text. There are 15 positives and 8 records without abstracts.

## Upstream sources

- CLEF-TAR 2019 Task 2 Testing DTA topics and qrels: [pinned CLEF-TAR source revision](https://github.com/CLEF-TAR/tar/tree/dbc13d02bb3e2f8ebc90e62ff47f5eb591e5ca20/2019-TAR/Task2/Testing/DTA).
- Review-specific DTA criteria: [pinned XITASO/lgar revision](https://github.com/XITASO/lgar/tree/49e94170dd0ff9380d8dfefecf8eec4692e8f05d/implementation/data/tar2019/dta).
- PubMed metadata: [NCBI E-utilities](https://www.ncbi.nlm.nih.gov/books/NBK25501/). The repository omits abstract text; PMIDs identify the source records.
- Donners_2021 dataset details and citation are in `data/synergy-dataset-1.0/Donners_2021/CITATION.txt`. The original dataset package is not redistributed here.

Exact DTA source revisions and original source-file checksums are in `dta_source_manifest.json`. Released score hashes, row counts, and data columns are in `released_data_manifest.json`.

## Redistribution

These compact score tables are derived research artifacts containing model outputs, record identifiers, benchmark labels, and usage metadata. They omit article titles and abstracts. Users retrieving source records should follow PubMed, publisher, CLEF-TAR, criteria-source, and ASReview dataset terms. No code or data license has been added; upstream sources retain their own terms.\n