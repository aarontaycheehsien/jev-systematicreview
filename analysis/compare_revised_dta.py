"""Strict, paired comparison of saved original and freshly scored revised holistic DTA Jev runs.

This script makes NO Jev calls and does not download article text.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from evaluate_dta import REVIEW_IDS, evaluate_review

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "data" / "jev_dta_scores.csv"
REVISED = ROOT / "outputs" / "dta_revised" / "dta_record_scores.csv"
CACHE = ROOT / "data" / "pubmed_metadata_cache.json"
EXPECTED_BASELINE_GIT_BLOB = "fb8d8cf4d178ba31f7d44fa536023f070b462ac0"
MEASURES = ("WSS@95", "WSS@100", "MAP", "Recall@5%", "Recall@10%", "Recall@20%", "Recall@50%")


def git_blob_id(raw: bytes) -> str:
    """Hash the same bytes as Git's blob object (portable across LF/CRLF checkouts)."""
    return hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()


def read_and_validate(baseline_path: Path, revised_path: Path, allow_model_change: bool) -> tuple[pd.DataFrame, list[str], list[str]]:
    baseline_bytes = baseline_path.read_bytes()
    canonical_bytes = baseline_bytes.replace(b"\r\n", b"\n")
    if EXPECTED_BASELINE_GIT_BLOB not in {git_blob_id(baseline_bytes), git_blob_id(canonical_bytes)}:
        raise ValueError("Baseline score file differs from the published Git blob; do not silently compare changed inputs.")
    original = pd.read_csv(baseline_path, dtype={"review_id": str, "pmid": str})
    revised = pd.read_csv(revised_path, dtype={"review_id": str, "pmid": str})
    original_required = {"review_id", "pmid", "label_included", "jev_probability", "jev_model", "abstract_available"}
    revised_required = {"review_id", "pmid", "label_included", "jev_probability", "jev_model", "error"}
    for name, table, required in (("original", original, original_required), ("revised", revised, revised_required)):
        if missing := required - set(table.columns):
            raise ValueError(f"{name} is missing columns: {sorted(missing)}")
        if table.duplicated(["review_id", "pmid"]).any():
            raise ValueError(f"Duplicate review/PMID keys in {name}")
        if set(table.review_id) != set(REVIEW_IDS):
            raise ValueError(f"{name} contains an unexpected set of review IDs")
        if len(table) != 30521 or int(table.label_included.sum()) != 440:
            raise ValueError(f"{name}: expected 30,521 pairs and 440 positive labels, got {len(table)} and {table.label_included.sum()}")
        if table.jev_probability.isna().any() or not table.jev_probability.between(0, 1).all():
            raise ValueError(f"{name}: missing or invalid Jev probabilities")
    if revised.error.fillna("").astype(str).str.strip().ne("").any():
        raise ValueError("The revised run has unresolved retrieval/API errors; resume scoring first.")
    original["abstract_available"] = original.abstract_available.astype(str).str.lower().map(
        {"true": True, "false": False, "1": True, "0": False}
    )
    if original.abstract_available.isna().any():
        raise ValueError("Original abstract availability must be Boolean")
    paired = original[["review_id", "pmid", "label_included", "abstract_available",
                       "jev_probability", "jev_model"]].merge(
        revised[["review_id", "pmid", "label_included", "jev_probability", "jev_model"]],
        on=["review_id", "pmid"], how="outer", validate="one_to_one",
        suffixes=("_original", "_revised"), indicator=True
    )
    if not paired._merge.eq("both").all() or len(paired) != 30521:
        raise ValueError("The original and revised runs do not cover identical review/PMID pairs.")
    if not paired.label_included_original.eq(paired.label_included_revised).all():
        raise ValueError("Original/revised qrel labels differ.")
    old_models = sorted(paired.jev_model_original.astype(str).unique().tolist())
    new_models = sorted(paired.jev_model_revised.astype(str).unique().tolist())
    if old_models != new_models and not allow_model_change:
        raise ValueError(f"Model change confounds the prompt comparison: original={old_models}, revised={new_models}; --allow-model-change to report with this caveat.")
    paired = paired.rename(columns={"label_included_original": "label_included"})
    return paired.drop(columns=["label_included_revised", "_merge"]), old_models, new_models


def check_pubmed_cache(paired: pd.DataFrame, cache_path: Path, skip_check: bool) -> str:
    if skip_check:
        return "PubMed availability check explicitly skipped; identical article text could not be verified."
    if not cache_path.is_file():
        raise FileNotFoundError(f"No PubMed cache at {cache_path}; restore the original cache or use --skip-cache-check with a prominently stated comparability caveat.")
    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    missing = set(paired.pmid) - set(cache)
    if missing:
        raise ValueError(f"PubMed cache missing {len(missing)} original PMIDs.")
    if any(bool(cache[pmid].get("retrieval_error")) for pmid in set(paired.pmid)):
        raise ValueError("PubMed cache has unresolved retrieval errors.")
    flags = paired.pmid.map(lambda x: bool(str(cache[x].get("abstract") or "").strip()))
    if not flags.eq(paired.abstract_available).all():
        raise ValueError("Abstract availability differs from the original run. Do not compare without resolving source-text drift.")
    return "Every PMID is cached, and abstract availability matches the published original. Original article text hashes were not retained, so exact text identity cannot be proved."


def evaluate_scope(paired: pd.DataFrame, scope: str):
    source = paired if scope == "all" else paired.loc[paired.abstract_available]
    rows = []
    for rid in REVIEW_IDS:
        subset = source.loc[source.review_id.eq(rid)]
        row = {"scope": scope, "review_id": rid, "n": len(subset),
               "positives": int(subset.label_included.sum())}
        for variant in ("original", "revised"):
            data = subset[["review_id", "pmid", "label_included",
                           f"jev_probability_{variant}"]].rename(
                columns={f"jev_probability_{variant}": "jev_probability"})
            result, _ = evaluate_review(data, rid)
            for measure in MEASURES:
                row[f"{variant}_{measure}"] = result[measure]
        for measure in MEASURES:
            row[f"delta_{measure}"] = row[f"revised_{measure}"] - row[f"original_{measure}"]
        rows.append(row)
    return pd.DataFrame(rows)


def plot_results(metrics: pd.DataFrame, scope: str, output: Path) -> None:
    fig, ax = plt.subplots(figsize=(11, 5))
    x = list(range(len(metrics)))
    ax.bar([v-0.2 for v in x], metrics["original_WSS@95"], width=0.4, label="Original")
    ax.bar([v+0.2 for v in x], metrics["revised_WSS@95"], width=0.4, label="Revised")
    ax.set_xticks(x, metrics.review_id, rotation=35, ha="right")
    ax.set(ylabel="WSS@95", title=f"Original versus revised Jev: {scope} DTA records")
    ax.legend()
    fig.tight_layout()
    fig.savefig(output / f"wss95_original_vs_revised_{scope}.png", dpi=160)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original", type=Path, default=BASELINE)
    parser.add_argument("--revised", type=Path, default=REVISED)
    parser.add_argument("--pubmed-cache", type=Path, default=CACHE)
    parser.add_argument("--output-dir", type=Path, default=ROOT/"results"/"revised_comparison")
    parser.add_argument("--skip-cache-check", action="store_true")
    parser.add_argument("--allow-model-change", action="store_true")
    args = parser.parse_args()
    paired, old_models, new_models = read_and_validate(
        args.original, args.revised, args.allow_model_change
    )
    cache_note = check_pubmed_cache(paired, args.pubmed_cache, args.skip_cache_check)
    filtered = paired.loc[paired.abstract_available]
    if (len(filtered), int(filtered.label_included.sum())) != (26832, 423):
        raise ValueError("The filtered cohort differs from the published original 26,832 / 423.")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    paired["probability_difference"] = paired.jev_probability_revised - paired.jev_probability_original
    paired.to_csv(args.output_dir/"paired_scores.csv", index=False)
    metrics = pd.concat([evaluate_scope(paired, "all"), evaluate_scope(paired, "nonmissing")],
                        ignore_index=True)
    baseline_mean = metrics.loc[metrics.scope.eq("nonmissing"), "original_WSS@95"].mean()
    if abs(baseline_mean - 0.6479776529047265) > 1e-9:
        raise ValueError(f"Baseline filtered macro WSS@95 does not reproduce: {baseline_mean}")
    metrics.to_csv(args.output_dir/"review_metrics.csv", index=False)
    aggregate = []
    for scope, table in metrics.groupby("scope", sort=False):
        item = {"scope": scope, "n": int(table.n.sum()),
                "positives": int(table.positives.sum())}
        for measure in MEASURES:
            for variant in ("original", "revised", "delta"):
                series = table[f"{variant}_{measure}"]
                item[f"{variant}_{measure}_macro_mean"] = float(series.mean())
                item[f"{variant}_{measure}_review_sd"] = float(series.std(ddof=1))
        aggregate.append(item)
        plot_results(table, scope, args.output_dir)
    pd.DataFrame(aggregate).to_csv(args.output_dir/"aggregate_metrics.csv", index=False)
    metadata = {
        "original_sha256": hashlib.sha256(args.original.read_bytes()).hexdigest(),
        "revised_sha256": hashlib.sha256(args.revised.read_bytes()).hexdigest(),
        "cache_check": cache_note, "original_models": old_models, "revised_models": new_models,
        "model_change_allowed": args.allow_model_change,
        "original_and_revised_have_identical_review_pmid_pairs": True,
        "ranking": "Within review, descending retain probability; ties ascending numeric PMID, then PMID text.",
        "wss95": "1 - ceil95_positive_rank/N - 0.05",
        "macro_aggregation": "Unweighted mean of eight review-level metrics.",
        "inference_calls": 0
    }
    (args.output_dir/"comparison_metadata.json").write_text(
        json.dumps(metadata, indent=2)+"\n", encoding="utf-8")
    lines = ["# Paired holistic Jev DTA comparison", "",
             "The original/revised comparison below is descriptive and retrospective.",
             "Both versions rank identical review-record pairs; the 95% recall cutoff is computed",
             "from known qrel labels after scoring, not a prospective deployment threshold.", "",
             f"Original model(s): {', '.join(old_models)}. Revised model(s): {', '.join(new_models)}.",
             cache_note, "",
             "| Cohort | N | Positives | Original WSS@95 | Revised WSS@95 | Difference (pp) |",
             "|---|---:|---:|---:|---:|---:|"]
    for item in aggregate:
        lines.append(f"| {item['scope']} | {item['n']:,} | {item['positives']} | "
                     f"{item['original_WSS@95_macro_mean']:.4f} | "
                     f"{item['revised_WSS@95_macro_mean']:.4f} | "
                     f"{100*item['delta_WSS@95_macro_mean']:+.2f} |")
    lines += ["", "See review_metrics.csv for per-review WSS@95, WSS@100, MAP,",
              "recall cutoffs and paired differences. All aggregate values are macro-averages.",
              "Published-system results are not head-to-head comparisons.",
              "If the model version or source texts changed, differences cannot be attributed solely to request organisation.",
              ""]
    (args.output_dir/"README.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
