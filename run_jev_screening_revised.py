"""Controlled Jev screening rerun with eligibility criteria in Noul instructions."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("SYNERGY_SET", "synergy")

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from synergy_dataset import Dataset, download_raw_subset

ROOT = Path(__file__).resolve().parent
DATA_ROOT = ROOT / "data" / "synergy-dataset-1.0"
OUTPUTS = ROOT / "outputs_revised"
RESULTS = OUTPUTS / "jev_results.csv"
COMPARISON = ROOT / "comparison_original_vs_revised"
ORIGINAL_RESULTS = ROOT / "outputs" / "jev_results.csv"
REVIEW_QUESTION = "Based ONLY on the supplied title and abstract, should this record be retained for further human screening for this systematic review?"
ELIGIBILITY = """Systematic-review eligibility criteria:

Retain the record if the title and abstract indicate that the study meets,
or may plausibly meet, BOTH of the following:

1. The study concerns emicizumab and provides data on humans.

2. The study provides original pharmacokinetic data, modelled
pharmacokinetic data, or pharmacokinetic/pharmacodynamic relationships.

If the title or abstract does not provide enough information to confidently
exclude the record, retain it for human screening.

Exclude only when the record clearly fails one or more criteria."""
TRUE_CRITERION = "Retain for human screening; the title/abstract meets or may plausibly meet the stated criteria, or is insufficient to exclude confidently."
FALSE_CRITERION = "Confidently exclude; the title/abstract clearly fails at least one stated criterion."


def load_dataset() -> pd.DataFrame:
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    dataset_path = DATA_ROOT / "Donners_2021"
    if not dataset_path.exists():
        download_raw_subset("Donners_2021", path=DATA_ROOT.parent)
    dataset = Dataset("Donners_2021", path=dataset_path)
    raw = dataset.to_frame(vars=["title", "abstract_original"])
    raw = raw.rename(columns={"openalex_id": "record_id", "abstract_original": "abstract"})
    raw["record_id"] = raw["record_id"].fillna("").astype(str)
    missing_id = raw["record_id"].eq("")
    raw.loc[missing_id, "record_id"] = raw.loc[missing_id].apply(
        lambda row: hashlib.sha256(f"{row['title']}\n{row['abstract']}".encode("utf-8")).hexdigest(), axis=1
    )
    raw["label_included"] = pd.to_numeric(raw["label_included"], errors="raise").astype(int)
    return raw[["record_id", "title", "abstract", "label_included"]]


def validate_dataset(df: pd.DataFrame) -> None:
    print("DATASET VALIDATION (SYNERGY Donners_2021)")
    print(f"Shape: {df.shape}")
    print("Columns: record_id, title, abstract, label_included")
    print("Title field: title")
    print("Abstract field: abstract (reconstructed from SYNERGY abstract_original index)")
    print("Final inclusion label: label_included")
    print(f"Ultimately included: {int(df.label_included.sum())}")
    print(f"Ultimately excluded: {int((df.label_included == 0).sum())}")
    print(f"Missing abstracts: {int(df.abstract.isna().sum())}")
    print("Labels are withheld from Jev state and question.")


def make_question():
    from typesafe_sdk import Noul

    return Noul(
        instructions=f"{ELIGIBILITY}\n\n{REVIEW_QUESTION}",
        criteria={"true": TRUE_CRITERION, "false": FALSE_CRITERION},
    )


def request_payload(row) -> dict:
    abstract = "[ABSTRACT MISSING]" if pd.isna(row.abstract) or not str(row.abstract).strip() else str(row.abstract)
    title = "" if pd.isna(row.title) else str(row.title)
    return {"title": title, "abstract": abstract}


def inspect_request(df: pd.DataFrame) -> None:
    """Print one representative input without creating a client or making an API call."""
    row = next(df.itertuples(index=False))
    from typesafe_sdk import Noul

    question = Noul(instructions=f"{ELIGIBILITY}\n\n{REVIEW_QUESTION}", criteria={"true": TRUE_CRITERION, "false": FALSE_CRITERION})
    payload = {
        "state": request_payload(row),
        "questions": {
            "retain": {
                "instructions": question.instructions,
                "criteria": question.criteria,
            }
        },
    }
    print("Representative client.system_one request (no API call):")
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


def evaluate(client, row) -> dict:
    state = request_payload(row)
    started = time.perf_counter()
    response = client.system_one(state=state, questions={"retain": make_question()})
    latency = time.perf_counter() - started
    answer = response.answers["retain"]
    probability = float(answer.noul)
    if not 0 <= probability <= 1:
        raise ValueError(f"Noul probability outside [0,1]: {probability}")
    usage = response.usage
    return {
        "record_id": row.record_id,
        "title": row.title,
        "abstract": row.abstract,
        "label_included": int(row.label_included),
        "jev_probability": probability,
        "jev_model": response.model,
        "input_tokens": getattr(usage, "input_tokens", None),
        "output_tokens": getattr(usage, "output_tokens", None),
        "latency_seconds": latency,
        "error": "",
    }


def read_results() -> pd.DataFrame:
    if RESULTS.exists():
        return pd.read_csv(RESULTS)
    return pd.DataFrame(columns=["record_id", "title", "abstract", "label_included", "jev_probability", "jev_model", "input_tokens", "output_tokens", "latency_seconds", "error"])


def smoke_sample(df: pd.DataFrame) -> pd.DataFrame:
    positive = df[df.label_included == 1].sort_values("record_id").head(1)
    negative = df[df.label_included == 0].sort_values("record_id").head(1)
    reserved = set(pd.concat([positive, negative]).record_id)
    ordinary = df[~df.record_id.isin(reserved)].sort_values("record_id").head(3)
    return pd.concat([positive, negative, ordinary]).drop_duplicates("record_id")


def write_results(rows: list[dict]) -> None:
    OUTPUTS.mkdir(parents=True, exist_ok=True)
    existing = read_results()
    combined = pd.concat([existing, pd.DataFrame(rows)], ignore_index=True)
    combined = combined.drop_duplicates("record_id", keep="last")
    combined.to_csv(RESULTS, index=False, encoding="utf-8-sig")


def run_calls(df: pd.DataFrame, smoke: bool) -> pd.DataFrame:
    if not os.environ.get("TYPESAFE_API_KEY"):
        raise RuntimeError("Set TYPESAFE_API_KEY in the environment before calling Jev.")
    from typesafe_sdk import TypeSafeClient

    cached = read_results()
    selected = smoke_sample(df) if smoke else df
    done = set(cached.loc[cached.error.fillna("").eq(""), "record_id"].astype(str))
    selected = selected[~selected.record_id.astype(str).isin(done)]
    pending = []
    with TypeSafeClient() as client:
        for row in selected.itertuples(index=False):
            record_id = str(row.record_id)
            for attempt in range(4):
                try:
                    result = evaluate(client, row)
                    pending.append(result)
                    write_results(pending)
                    pending.clear()
                    print(f"Done {record_id}: P(retain)={result['jev_probability']:.4f}; model={result['jev_model']}", flush=True)
                    break
                except Exception as exc:
                    if attempt == 3:
                        pending.append({"record_id": record_id, "title": row.title, "abstract": row.abstract, "label_included": int(row.label_included), "jev_probability": None, "jev_model": None, "input_tokens": None, "output_tokens": None, "latency_seconds": None, "error": f"{type(exc).__name__}: {exc}"})
                        write_results(pending)
                        pending.clear()
                        print(f"FAILED {record_id}: {type(exc).__name__}: {exc}", flush=True)
                    else:
                        time.sleep(2**attempt)
    results = read_results()
    if smoke:
        subset = results[results.record_id.isin(smoke_sample(df).record_id)].copy()
        print("\nSMOKE TEST: title | final inclusion label | Jev P(true=retain) | model")
        for row in subset.itertuples(index=False):
            print(f"{row.title} | {row.label_included} | {row.jev_probability} | {row.jev_model}")
        if subset.error.fillna("").ne("").any() or subset.jev_probability.isna().any():
            print("Smoke test contains API failures; fix before full run.")
    return results


def evaluate_thresholds(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    labels = df.label_included.astype(int)
    probs = pd.to_numeric(df.jev_probability, errors="coerce")
    for threshold in [i / 10 for i in range(1, 10)]:
        retained = probs >= threshold
        tp = int(((labels == 1) & retained).sum())
        fn = int(((labels == 1) & ~retained).sum())
        tn = int(((labels == 0) & ~retained).sum())
        fp = int(((labels == 0) & retained).sum())
        total = len(df)
        rows.append({"threshold": threshold, "true_positives": tp, "false_negatives": fn, "true_negatives": tn, "false_positives": fp,
                     "recall": tp / (tp + fn) if tp + fn else float("nan"),
                     "specificity": tn / (tn + fp) if tn + fp else float("nan"),
                     "precision": tp / (tp + fp) if tp + fp else float("nan"),
                     "retained_for_human_screening": int(retained.sum()),
                     "automatically_excluded": int((~retained).sum()),
                     "workload_reduction_pct": float((~retained).sum() / total * 100)})
    return pd.DataFrame(rows)


def summarize_and_plot(df: pd.DataFrame) -> None:
    OUTPUTS.mkdir(parents=True, exist_ok=True)
    thresholds = evaluate_thresholds(df)
    thresholds.to_csv(OUTPUTS / "threshold_results.csv", index=False)
    scored = df.dropna(subset=["jev_probability"]).copy()
    included = scored[scored.label_included == 1]
    excluded = scored[scored.label_included == 0]
    min_positive = float(included.jev_probability.min())
    n = len(scored)
    oracle_retained = scored.jev_probability >= min_positive
    oracle = {"threshold": min_positive, "included_retained": int(((scored.label_included == 1) & oracle_retained).sum()),
              "included_missed": int(((scored.label_included == 1) & ~oracle_retained).sum()),
              "records_retained": int(oracle_retained.sum()), "excluded": int((~oracle_retained).sum()),
              "reduction": float((~oracle_retained).sum() / n * 100)}
    min_95 = included.jev_probability.sort_values().iloc[max(0, int((0.05 * len(included)) // 1))] if len(included) else float("nan")
    at50 = thresholds.loc[thresholds.threshold.eq(0.5)].iloc[0]
    included.sort_values("jev_probability").to_csv(OUTPUTS / "included_studies_ranked.csv", index=False, encoding="utf-8-sig")
    excluded.sort_values("jev_probability", ascending=False).head(10).to_csv(OUTPUTS / "highest_scoring_excluded.csv", index=False, encoding="utf-8-sig")
    fig, ax = plt.subplots(figsize=(7, 5))
    ax.plot(thresholds.workload_reduction_pct, thresholds.recall * 100, marker="o", label="Fixed thresholds")
    ax.scatter([oracle["reduction"]], [100], marker="*", s=160, color="crimson", label="Post-hoc 100% recall")
    ax.set(xlabel="Workload reduction (%)", ylabel="Recall of ultimately included studies (%)", xlim=(0, 100), ylim=(0, 105))
    ax.grid(alpha=.25); ax.legend(); fig.tight_layout(); fig.savefig(OUTPUTS / "recall_vs_workload.png", dpi=160); plt.close(fig)
    fig, ax = plt.subplots(figsize=(7, 5))
    ax.hist(excluded.jev_probability, bins=12, alpha=.65, label=f"Ultimately excluded (n={len(excluded)})")
    ax.hist(included.jev_probability, bins=12, alpha=.75, label=f"Ultimately included (n={len(included)})")
    ax.set(xlabel="Jev probability of retain", ylabel="Records", xlim=(0, 1)); ax.grid(axis="y", alpha=.25); ax.legend(); fig.tight_layout(); fig.savefig(OUTPUTS / "probability_distribution.png", dpi=160); plt.close(fig)
    failures = int(df.error.fillna("").ne("").sum())
    missing_abstract = int(df.abstract.isna().sum())
    runtime = float(pd.to_numeric(df.latency_seconds, errors="coerce").sum())
    in_tokens = pd.to_numeric(df.input_tokens, errors="coerce").sum()
    out_tokens = pd.to_numeric(df.output_tokens, errors="coerce").sum()
    model_values = ", ".join(sorted(str(x) for x in scored.jev_model.dropna().unique())) or "not available"
    summary = f"""# Jev screening experiment: Donners_2021 (revised request organization)

## Dataset

- Records: {len(df)}
- Ultimately included: {int(df.label_included.sum())}
- Ultimately excluded: {int((df.label_included == 0).sum())}
- Missing abstracts: {missing_abstract}

## Main result

At the **post-hoc/oracle 100%-recall threshold** of {min_positive:.4f}, Jev retained {oracle['included_retained']} of {int(df.label_included.sum())} ultimately included studies and would have automatically excluded {oracle['excluded']} of {n} scored records, a workload reduction of {oracle['reduction']:.1f}%.

This threshold was selected after examining the known labels and is therefore an oracle/post-hoc threshold, not a prospectively validated screening threshold. It describes separation in this retrospective dataset.

At the analogous post-hoc threshold of {min_95:.4f}, recall is at least 95% on this small set of {len(included)} positive cases.

## Fixed threshold: 0.50

- True positives: {int(at50.true_positives)}; false negatives: {int(at50.false_negatives)}
- True negatives: {int(at50.true_negatives)}; false positives: {int(at50.false_positives)}
- Recall: {at50.recall:.1%}; specificity: {at50.specificity:.1%}; precision: {at50.precision:.1%}
- Retained for human screening: {int(at50.retained_for_human_screening)}; automatically excluded: {int(at50.automatically_excluded)}
- Workload reduction: {at50.workload_reduction_pct:.1f}%

## Errors and runtime/API use

- API failures: {failures}
- Missing abstracts: {missing_abstract}
- Total measured Jev call latency: {runtime:.1f} seconds
- Input/output tokens: {int(in_tokens) if pd.notna(in_tokens) else 0} / {int(out_tokens) if pd.notna(out_tokens) else 0}
- Model(s) returned: {model_values}
- Failed API attempts: four initial 400 responses for the record with a missing title; after normalizing its structured-state title to an empty string, its retry succeeded. There are no unresolved record failures. Token totals include successful responses only.
- Approximate cost: not estimated (no pricing calculation included)

## Interpretation

This experiment asks whether Jev can identify studies that were ultimately included in this one review from title and abstract while reducing records sent to human screening. SYNERGY's label is final review inclusion, not the original title/abstract screening decision. The retrospective result does not establish an operational threshold or safe automation.
"""
    (OUTPUTS / "summary.md").write_text(summary, encoding="utf-8")


def compare_runs(revised: pd.DataFrame) -> None:
    original = pd.read_csv(ORIGINAL_RESULTS)
    original = original[original.error.fillna("").eq("") & original.jev_probability.notna()].copy()
    revised = revised[revised.error.fillna("").eq("") & revised.jev_probability.notna()].copy()
    paired = original[["record_id", "title", "label_included", "jev_probability", "jev_model"]].merge(
        revised[["record_id", "jev_probability", "jev_model"]], on="record_id", how="inner", suffixes=("_original", "_revised"))
    paired = paired.rename(columns={"jev_probability_original": "original_jev_probability", "jev_probability_revised": "revised_jev_probability", "jev_model_original": "original_jev_model", "jev_model_revised": "revised_jev_model"})
    paired["probability_difference"] = paired.revised_jev_probability - paired.original_jev_probability
    paired["absolute_probability_difference"] = paired.probability_difference.abs()
    COMPARISON.mkdir(parents=True, exist_ok=True)
    paired.to_csv(COMPARISON / "paired_results.csv", index=False, encoding="utf-8-sig")

    original_metrics = evaluate_thresholds(original)
    revised_metrics = evaluate_thresholds(revised)
    threshold_comparison = original_metrics.add_prefix("original_").merge(revised_metrics.add_prefix("revised_"), left_on="original_threshold", right_on="revised_threshold")
    threshold_comparison.to_csv(COMPARISON / "threshold_comparison.csv", index=False)

    x = paired.original_jev_probability
    y = paired.revised_jev_probability
    diff = paired.probability_difference
    absolute = paired.absolute_probability_difference
    boundaries = [(0, .01, "<0.01"), (.01, .05, "0.01–<0.05"), (.05, .10, "0.05–<0.10"), (.10, float("inf"), "≥0.10")]
    bins = [(label, int(((absolute >= lower) & (absolute < upper)).sum())) for lower, upper, label in boundaries]
    models_original = ", ".join(sorted(original.jev_model.dropna().astype(str).unique())) or "not available"
    models_revised = ", ".join(sorted(revised.jev_model.dropna().astype(str).unique())) or "not available"
    mean_abs = float(absolute.mean())
    median_abs = float(absolute.median())
    max_abs = float(absolute.max())
    pearson = float(x.corr(y, method="pearson")) if len(paired) > 1 else float("nan")
    spearman = float(x.rank(method="average").corr(y.rank(method="average"), method="pearson")) if len(paired) > 1 else float("nan")
    summary_lines = [
        "# Original vs revised Jev screening comparison", "",
        "## Paired scores", "",
        f"- Successfully matched records: {len(paired)} (original successful: {len(original)}; revised successful: {len(revised)})",
        f"- Model returned, original: {models_original}", f"- Model returned, revised: {models_revised}",
        f"- Mean Jev probability, original: {x.mean():.4f}", f"- Mean Jev probability, revised: {y.mean():.4f}",
        f"- Median Jev probability, original: {x.median():.4f}", f"- Median Jev probability, revised: {y.median():.4f}",
        f"- Mean absolute change: {mean_abs:.4f}", f"- Median absolute change: {median_abs:.4f}", f"- Maximum absolute change: {max_abs:.4f}",
        f"- Pearson correlation: {pearson:.4f}", f"- Spearman rank correlation: {spearman:.4f}", "",
        "### Absolute probability change", "", "| Absolute change | Records | Percentage |", "|---|---:|---:|",
    ]
    summary_lines += [f"| {label} | {count} | {count / len(paired) * 100:.1f}% |" for label, count in bins]
    summary_lines += ["", "## Screening performance", "", "Fixed-threshold figures use the same evaluation logic as the original runner: retain when probability ≥ threshold, thresholds 0.1 through 0.9, with recall, specificity, precision, and workload reduction reported in `threshold_comparison.csv`.", "", "The 100%-recall oracle threshold is computed separately for each run as the minimum probability among ultimately included records. It uses the known final inclusion labels and is descriptive post-hoc analysis. Fixed-threshold and oracle results are retrospective; none is prospective performance or a validated operational threshold.", ""]
    summary_lines += ["### At fixed threshold 0.50", "", "| Run | Recall | Specificity | Precision | Workload reduction |", "|---|---:|---:|---:|---:|"]
    for name, metrics in (("Original", original_metrics), ("Revised", revised_metrics)):
        row = metrics.loc[metrics.threshold.eq(.5)].iloc[0]
        summary_lines.append(f"| {name} | {row.recall:.1%} | {row.specificity:.1%} | {row.precision:.1%} | {row.workload_reduction_pct:.1f}% |")
    summary_lines += ["", "### Post-hoc/oracle 100%-recall threshold", "", "| Run | Threshold | Recall | Specificity | Precision | Workload reduction |", "|---|---:|---:|---:|---:|---:|"]
    for name, run in (("Original", original), ("Revised", revised)):
        t = float(run.loc[run.label_included.eq(1), "jev_probability"].min())
        retained = run.jev_probability >= t
        labels = run.label_included.astype(int)
        tp = int(((labels == 1) & retained).sum()); tn = int(((labels == 0) & ~retained).sum()); fp = int(((labels == 0) & retained).sum())
        rec = tp / int((labels == 1).sum()) if (labels == 1).sum() else float("nan")
        spec = tn / int((labels == 0).sum()) if (labels == 0).sum() else float("nan")
        prec = tp / (tp + fp) if tp + fp else float("nan")
        reduction = float((~retained).sum() / len(run) * 100)
        summary_lines.append(f"| {name} | {t:.4f} | {rec:.1%} | {spec:.1%} | {prec:.1%} | {reduction:.1f}% |")
    summary_lines += ["", "## Run comparability", "", f"- Original rows: {len(original)} successful scores; revised rows: {len(revised)} successful scores.", f"- Token totals, original input/output: {pd.to_numeric(original.input_tokens, errors='coerce').sum():.0f} / {pd.to_numeric(original.output_tokens, errors='coerce').sum():.0f}; revised: {pd.to_numeric(revised.input_tokens, errors='coerce').sum():.0f} / {pd.to_numeric(revised.output_tokens, errors='coerce').sum():.0f}.", f"- Unresolved recorded failures, original: {int(pd.read_csv(ORIGINAL_RESULTS).error.fillna('').ne('').sum())}; revised: {int(pd.read_csv(RESULTS).error.fillna('').ne('').sum())}.", "- Four initial revised-run API attempts for one missing-title record returned 400 (NaN/infinity); normalizing the title to an empty string fixed the structured-state serialization, and a retry succeeded. Failed attempts returned no usage values, so reported revised token totals include successful responses only.", "- Probability changes describe sensitivity to request organization. They do not by themselves establish a better or worse screening result.", ""]
    (COMPARISON / "comparison_summary.md").write_text("\n".join(summary_lines), encoding="utf-8")

    fig, ax = plt.subplots(figsize=(6.5, 6))
    ax.scatter(x, y, alpha=.65, s=24)
    ax.plot([0, 1], [0, 1], linestyle="--", color="black", linewidth=1, label="y=x")
    ax.set(xlabel="Original Jev probability", ylabel="Revised Jev probability", xlim=(0, 1), ylim=(0, 1), title="Paired Jev probabilities")
    ax.grid(alpha=.25); ax.legend(); fig.tight_layout(); fig.savefig(COMPARISON / "probability_scatter.png", dpi=160); plt.close(fig)
    fig, ax = plt.subplots(figsize=(7, 5))
    ax.hist(diff, bins=20, edgecolor="white")
    ax.axvline(0, color="black", linestyle="--", linewidth=1)
    ax.set(xlabel="Revised − original Jev probability", ylabel="Records", title="Distribution of paired probability changes")
    ax.grid(axis="y", alpha=.25); fig.tight_layout(); fig.savefig(COMPARISON / "probability_difference_distribution.png", dpi=160); plt.close(fig)
    fig, ax = plt.subplots(figsize=(7, 5))
    for name, metrics in (("Original", original_metrics), ("Revised", revised_metrics)):
        ax.plot(metrics.workload_reduction_pct, metrics.recall * 100, marker="o", label=name)
    ax.set(xlabel="Workload reduction (%)", ylabel="Recall of ultimately included studies (%)", xlim=(0, 100), ylim=(0, 105), title="Recall versus workload reduction")
    ax.grid(alpha=.25); ax.legend(); fig.tight_layout(); fig.savefig(COMPARISON / "recall_vs_workload.png", dpi=160); plt.close(fig)
    print(f"Comparison written to {COMPARISON}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--validate", action="store_true", help="inspect the source data without calling Jev")
    group.add_argument("--inspect-request", action="store_true", help="print one representative request without calling Jev")
    group.add_argument("--smoke", action="store_true", help="run the five-record smoke test")
    group.add_argument("--full", action="store_true", help="run all records and create revised and comparison outputs")
    args = parser.parse_args()
    df = load_dataset()
    validate_dataset(df)
    OUTPUTS.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUTPUTS / "source_records.csv", index=False, encoding="utf-8-sig")
    if args.validate:
        return 0
    if args.inspect_request:
        inspect_request(df)
        return 0
    if args.smoke:
        results = run_calls(df, smoke=True)
        sample = results[results.record_id.isin(smoke_sample(df).record_id)]
        return 0 if len(sample) == 5 and sample.error.fillna("").eq("").all() and sample.jev_probability.notna().all() and sample.jev_model.notna().all() else 2
    results = run_calls(df, smoke=False)
    completed = results[results.error.fillna("").eq("") & results.jev_probability.notna()].copy()
    if len(completed) != len(df):
        print(f"Full run has {len(df) - len(completed)} records without successful scores. Results were saved for resume; evaluation outputs need all records.")
        return 2
    summarize_and_plot(completed)
    compare_runs(completed)
    print(f"Complete. Revised outputs are in {OUTPUTS}; comparison outputs are in {COMPARISON}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
