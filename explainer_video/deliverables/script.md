# Club Eligibility: The $1.46 Bouncer

3:45 animated explainer • 445 spoken words • conference-safe satire

Source: [Aaron Tay, 1 October 2026](https://aarontay.substack.com/p/can-jev-a-super-cheap-super-fast)

Jev has no spoken dialogue. The soundtrack is original synthesized music; character voices use local Windows speech synthesis.

## 00:00 — Just a quick review

**00:02 · Narrator**
Every systematic review begins with a perfectly reasonable request.

**00:09 · PI**
Just a quick review. Shouldn't take long.

**00:14 · Narrator**
Then the abstracts arrive. The search was comprehensive. Unfortunately, so were the consequences. Welcome to Club Eligibility. Full text upstairs.

## 00:25 — The expensive talent

**00:26 · Narrator**
The generative model arrives with an entourage, a limousine, and the ability to turn one screening decision into a TED Talk.

**00:35 · LLM**
Before deciding whether to retain this abstract, we must consider the epistemological status of relevance.

**00:42 · Librarian**
You've written more about whether to read the abstract than the authors wrote in the abstract.

**00:50 · Narrator**
Jev arrives with a folding stool. Jev does decisions.

## 00:55 — The receipt reveal

**00:56 · Narrator**
Give this zero-shot classifier the title, abstract, and eligibility criteria. It returns a structured decision with probabilities. No bespoke training. No free-text monologue. Here, one question orders the queue for human screening.

**01:08 · Narrator**
Eight diagnostic test accuracy reviews. Twenty-six thousand, eight hundred and thirty-two records with abstracts. Mean WSS at ninety-five: zero point six six one.

**01:17 · Narrator**
That's work saved over sampling at ninety-five percent recall, measured retrospectively. It isn't accuracy. Performance varies by review. The article reports a bill of about one dollar forty-six.

**01:29 · Librarian**
Finally, research infrastructure we can expense without forming a steering committee.

## 01:35 — The ensemble VIPs

**01:36 · Narrator**
The published three-model ensemble does better: zero point six eight zero. Add embedding reranking: zero point seven zero eight. Jev remains impressively competitive for something with less furniture.

**01:48 · Librarian**
Three models, one decision. A committee meeting with measurable output. Unsettling. Please record this unprecedented event in the minutes.

**01:58 · Narrator**
These are published benchmark comparisons, using older models. Today's competitors may change the picture.

## 02:05 — Management improves things

**02:06 · Narrator**
Management spots an opportunity for improvement. Replace the single overall question with five criterion questionnaires. Five times the judgements. Surely that means better screening?

**02:17 · Narrator**
In this tested setup, the probability-based expected-score variant reaches only zero point five three six. More machinery. Worse ranking.

**02:25 · Librarian**
We added bureaucracy and performance got worse. Finally, AI understands academia.

**02:33 · Narrator**
The questions or scoring might be the problem. That's a hypothesis. Decomposition hasn't been convicted.

## 02:40 — One question

**02:41 · Librarian**
One question. How do you know when to stop screening?

**02:48 · Narrator**
The evaluator consults the known benchmark labels. Those labels locate the ninety-five percent recall point after scoring. Jev never sees them. A retrospective result doesn't give a new review a validated stopping rule.

**03:01 · Librarian**
Excellent crystal ball. Does it work before we know which studies are relevant? My protocol has a surprisingly strict policy on clairvoyance.

**03:11 · Narrator**
Before trusting automated exclusions, prospectively validate thresholds, calibration, and stopping rules. Test other review types too. A probability needs checking, and eight DTA reviews aren't the whole evidence-synthesis universe.

**03:24 · Paper**
The methods are in the full text.

**03:29 · Librarian**
Of course they are. Heaven forbid the abstract become useful.

**03:38 · Narrator**
Jev works the queue. The librarian keeps the keys. Cheap decisions. Expensive questions.

## Fact and interpretation notes

- 0.661 is the unweighted mean of eight revised review-level WSS@95 values; it is not pooled accuracy or a validated prospective saving.
- The main benchmark contains 26,832 review-record pairs with abstracts and 423 relevant labels. The bar chart uses the revised September 30 run, not the earlier README baseline.
- The article reports approximately US$1.46. The receipt is labelled as a reported run cost, not a tariff or an all-inclusive price for a live review.
- Ensemble scores 0.680 and 0.708 are published benchmark comparisons reported in the article; the cartoon does not imply a newly controlled head-to-head experiment.
- 0.536 refers to the Jev-QA-Expected variant (0.5358 rounded), not the hard-answer variant. Possible causes are explicitly hypotheses.
- Gold labels are evaluation-only. The oracle scene depicts the evaluator consulting labels after scoring, never supplying labels to Jev.
- The classification output p(retain) = 0.87 is illustrative. Calibration on this task has not been established.
- Thresholds, calibration, stopping rules, and generalization require further prospective validation.
