# Jev screening experiment: Donners_2021 (revised request organization)

## Dataset

- Records: 258
- Ultimately included: 15
- Ultimately excluded: 243
- Missing abstracts: 8

## Main result

At the **post-hoc/oracle 100%-recall threshold** of 0.3600, Jev retained 15 of 15 ultimately included studies and would have automatically excluded 118 of 258 scored records, a workload reduction of 45.7%.

This threshold was selected after examining the known labels and is therefore an oracle/post-hoc threshold, not a prospectively validated screening threshold. It describes separation in this retrospective dataset.

At the analogous post-hoc threshold of 0.3600, recall is at least 95% on this small set of 15 positive cases.

## Fixed threshold: 0.50

- True positives: 13; false negatives: 2
- True negatives: 156; false positives: 87
- Recall: 86.7%; specificity: 64.2%; precision: 13.0%
- Retained for human screening: 100; automatically excluded: 158
- Workload reduction: 61.2%

## Errors and runtime/API use

- API failures: 0
- Missing abstracts: 8
- Total measured Jev call latency: 73.0 seconds
- Input/output tokens: 267820 / 5160
- Model(s) returned: jev-1.13.0
- Failed API attempts: four initial 400 responses for the record with a missing title; after normalizing its structured-state title to an empty string, its retry succeeded. There are no unresolved record failures. Token totals include successful responses only.
- Approximate cost: not estimated (no pricing calculation included)

## Interpretation

This experiment asks whether Jev can identify studies that were ultimately included in this one review from title and abstract while reducing records sent to human screening. SYNERGY's label is final review inclusion, not the original title/abstract screening decision. The retrospective result does not establish an operational threshold or safe automation.
