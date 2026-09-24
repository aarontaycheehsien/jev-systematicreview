# Donners_2021 saved-score evaluation

This evaluation recomputes threshold metrics from the released score file. **No Jev calls were made.** Input SHA-256: `1d8637214ea298c72456fbce602e1777e4a8f68934b2b635071b5e26729cf30a`.

## Dataset

- Records: 258
- Ultimately included: 15
- Ultimately excluded: 243
- Missing abstracts: 8
- Model: jev-1.13.0

## Post-hoc oracle description

At the label-informed 100%-recall threshold of 0.3300, all 15 ultimately included studies are retained and 124 of 258 records would be excluded, a workload reduction of 48.1%. This is a post-hoc description using the same labels, not a prospectively validated threshold.

## Fixed threshold 0.50

- True positives: 12; false negatives: 3
- True negatives: 179; false positives: 64
- Recall: 80.0%; specificity: 73.7%; precision: 15.8%
- Retained: 76; automatically excluded: 182
- Workload reduction: 70.5%

The benchmark label is final inclusion in one review, not a record of the original title/abstract screening decision. This retrospective single-review experiment does not validate autonomous screening.
