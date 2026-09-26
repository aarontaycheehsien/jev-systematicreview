"""Run the Jev QA condition against the saved filtered CLEF-TAR DTA set.

Questions must be transcribed without edits from Akinseloyin et al. (2024),
Appendix A, into outputs/jev_qa_2024_questions.json before scoring. Gold qrels
are deliberately loaded only after every Jev judgement has completed.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import math
import os
import sqlite3
import threading
import time
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from typesafe_sdk import Choice, TypeSafeClient

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "outputs" / "jev_qa_2024"
QUESTION_FILE = ROOT / "outputs" / "jev_qa_2024_questions.json"
FILTERED_RECORDS = ROOT / "outputs" / "dta_nonmissing_abstract_evaluation_2026-09-25" / "dta_record_scores_nonmissing_abstract.csv"
HOLISTIC = ROOT / "outputs" / "dta_nonmissing_abstract_evaluation_2026-09-25" / "dta_review_results_nonmissing_abstract.csv"
BASELINE_SCORES = ROOT / "outputs" / "dta_nonmissing_abstract_evaluation_2026-09-25" / "dta_record_scores_nonmissing_abstract.csv"
REVIEW_IDS = ["CD008874", "CD009044", "CD011686", "CD012080", "CD012233", "CD012567", "CD012669", "CD012768"]
MODEL = "jev-1.13.0"
INPUT_PRICE_PER_MILLION = 0.042
THREAD_LOCAL = threading.local()
CREDIT_BLOCKED = threading.Event()
CHOICE_CRITERIA = {
    "POSITIVE": "The supplied title and abstract provides information supporting a YES answer to the question and therefore compatibility with the criterion.",
    "NEUTRAL": "The supplied title and abstract does not provide enough information, or is too ambiguous, to give a confirmatory answer.",
    "NEGATIVE": "The supplied title and abstract provides a clear NO answer to the question, indicating incompatibility with the criterion.",
}


def question_list(row: dict) -> list[str]:
    if isinstance(row.get("questions"), list):
        return row["questions"]
    entries = [(key, value) for key, value in row.items() if len(key) > 1 and key[0] == "Q" and key[1:].isdigit()]
    return [value for _, value in sorted(entries, key=lambda kv: int(kv[0][1:]))]


def load_questions(path: Path) -> dict[str, dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    reviews = payload.get("reviews", payload)
    by_id = {row["review_id"]: row for row in reviews} if isinstance(reviews, list) else reviews
    if set(by_id) != set(REVIEW_IDS):
        raise ValueError(f"Question file must contain exactly these review IDs: {REVIEW_IDS}")
    for rid in REVIEW_IDS:
        row = by_id[rid]
        qs = question_list(row)
        criteria = row.get("original_eligibility_criteria", row)
        if not qs or any(not isinstance(q, str) or not q.strip() for q in qs):
            raise ValueError(f"{rid}: at least one non-empty exact question is required")
        if row.get("source") != "Akinseloyin et al. 2024 supplementary Appendix A":
            raise ValueError(f"{rid}: unexpected/missing source attribution")
        if not criteria.get("inclusion_criteria") or not criteria.get("exclusion_criteria"):
            raise ValueError(f"{rid}: original inclusion and exclusion criteria are required")
    return by_id


def open_client() -> TypeSafeClient:
    if not hasattr(THREAD_LOCAL, "client"):
        THREAD_LOCAL.client = TypeSafeClient()
    return THREAD_LOCAL.client


def init_db(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS judgements (
            review_id TEXT NOT NULL, pmid TEXT NOT NULL, question_number INTEGER NOT NULL,
            question TEXT NOT NULL, answer TEXT, p_positive REAL, p_neutral REAL, p_negative REAL,
            jev_model TEXT, input_tokens INTEGER, output_tokens INTEGER, latency_seconds REAL,
            error TEXT, PRIMARY KEY (review_id, pmid, question_number))""")


def completed_keys(path: Path) -> set[tuple[str, str, int]]:
    with sqlite3.connect(path) as conn:
        return set(conn.execute("SELECT review_id, pmid, question_number FROM judgements WHERE error = '' AND answer IS NOT NULL").fetchall())


def save_rows(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with sqlite3.connect(path) as conn:
        conn.executemany("""INSERT OR REPLACE INTO judgements
            (review_id,pmid,question_number,question,answer,p_positive,p_neutral,p_negative,
             jev_model,input_tokens,output_tokens,latency_seconds,error)
            VALUES (:review_id,:pmid,:question_number,:question,:answer,:p_positive,:p_neutral,
             :p_negative,:jev_model,:input_tokens,:output_tokens,:latency_seconds,:error)""", rows)


def judge_one(item: dict) -> dict:
    if CREDIT_BLOCKED.is_set():
        return {**item, "answer": None, "p_positive": None, "p_neutral": None, "p_negative": None,
                "jev_model": "", "input_tokens": None, "output_tokens": None, "latency_seconds": None,
                "error": "Skipped after provider reported no available TypeSafe API credits; retry after credits are available."}
    q = Choice(instructions=item["question"], criteria=CHOICE_CRITERIA)
    state = f"TITLE:\n{item['title']}\n\nABSTRACT:\n{item['abstract']}"
    last_error = ""
    elapsed_total = 0.0
    for attempt in range(4):
        started = time.perf_counter()
        try:
            response = open_client().system_one(state=state, questions={"answer": q}, model=MODEL)
            elapsed_total += time.perf_counter() - started
            answer = response.choices["answer"]
            probs = answer.probabilities
            pp, pn, pneg = (float(probs[k]) for k in ("POSITIVE", "NEUTRAL", "NEGATIVE"))
            if any(not math.isfinite(p) or p < 0 or p > 1 for p in (pp, pn, pneg)):
                raise ValueError(f"Invalid choice probability distribution: {probs}")
            if abs(pp + pn + pneg - 1) > .03:
                raise ValueError(f"Choice probabilities do not sum approximately to 1: {probs}")
            return {**item, "answer": answer.choice.upper(), "p_positive": pp, "p_neutral": pn,
                    "p_negative": pneg, "jev_model": response.model,
                    "input_tokens": response.usage.input_tokens, "output_tokens": response.usage.output_tokens,
                    "latency_seconds": elapsed_total, "error": ""}
        except Exception as exc:
            elapsed_total += time.perf_counter() - started
            last_error = f"{type(exc).__name__}: {exc}"
            if "402" in str(exc) and "no available TypeSafe API credits" in str(exc):
                CREDIT_BLOCKED.set()
                break
            if CREDIT_BLOCKED.is_set():
                break
            if attempt < 3:
                time.sleep(2 ** attempt)
    return {**item, "answer": None, "p_positive": None, "p_neutral": None, "p_negative": None,
            "jev_model": "", "input_tokens": None, "output_tokens": None,
            "latency_seconds": elapsed_total, "error": last_error}


def load_filtered_text() -> pd.DataFrame:
    # Select text/IDs at CSV-read time so gold labels and prior scores are not loaded during scoring.
    df = pd.read_csv(FILTERED_RECORDS, dtype={"pmid": str}, usecols=["review_id", "pmid", "title", "abstract"])
    need = {"review_id", "pmid", "title", "abstract"}
    if not need.issubset(df.columns):
        raise ValueError(f"Filtered input is missing {sorted(need-set(df.columns))}")
    # Deliberately discard label and all existing Jev scores before calling the API.
    df = df.loc[:, ["review_id", "pmid", "title", "abstract"]].copy()
    df = df[df.review_id.isin(REVIEW_IDS)]
    if df.duplicated(["review_id", "pmid"]).any() or df.title.isna().any() or df.abstract.isna().any():
        raise ValueError("Filtered set must have unique review/PMID pairs and available text")
    if df.abstract.astype(str).str.strip().eq("").any():
        raise ValueError("Filtered input includes an empty abstract")
    return df


def run_calls(questions: dict[str, dict], workers: int, db: Path) -> tuple[float, int]:
    records = load_filtered_text()
    init_db(db)
    done = completed_keys(db)
    total_expected = sum(len(question_list(questions[rid])) * int(records.review_id.eq(rid).sum()) for rid in REVIEW_IDS)
    requested = max(0, total_expected-len(done))
    print(f"Review-record pairs: {len(records)}; question judgements planned: {requested}; resumed: {len(done)}", flush=True)
    start = time.perf_counter()
    buffer: list[dict] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        batch: list[dict] = []
        completed_this_run = 0
        def flush_batch() -> None:
            nonlocal completed_this_run, buffer, batch
            futures=[pool.submit(judge_one,item) for item in batch]
            batch=[]
            for future in concurrent.futures.as_completed(futures):
                buffer.append(future.result())
                completed_this_run += 1
                if len(buffer)>=100:
                    save_rows(db,buffer)
                    buffer.clear()
                if completed_this_run % 1000==0:
                    print(f"Completed this run: {completed_this_run}/{requested} judgements; wall {time.perf_counter()-start:.0f}s",flush=True)
        for row in records.itertuples(index=False):
            if CREDIT_BLOCKED.is_set(): break
            for qi,question in enumerate(question_list(questions[row.review_id]),1):
                if CREDIT_BLOCKED.is_set(): break
                key=(row.review_id,str(row.pmid),qi)
                if key in done: continue
                batch.append({"review_id":row.review_id,"pmid":str(row.pmid),"question_number":qi,
                              "question":question,"title":row.title,"abstract":row.abstract})
                if len(batch)>=500: flush_batch()
            if CREDIT_BLOCKED.is_set(): break
        if batch: flush_batch()
    save_rows(db, buffer)
    if CREDIT_BLOCKED.is_set():
        print("Provider credit exhaustion detected; submitted no further calls. Saved successful and pending rows for resume.",flush=True)
    return time.perf_counter() - start, requested


def fetch_judgements(db: Path) -> pd.DataFrame:
    with sqlite3.connect(db) as conn:
        return pd.read_sql_query("SELECT * FROM judgements ORDER BY review_id, CAST(pmid AS INTEGER), question_number", conn, dtype={"pmid": str})


def evaluate(method_scores: pd.DataFrame, labels: pd.DataFrame, method: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    d = method_scores.merge(labels[["review_id", "pmid", "label_included"]], on=["review_id", "pmid"], validate="one_to_one")
    metric_rows, ranked = [], []
    for rid in REVIEW_IDS:
        g = d[d.review_id.eq(rid)].copy()
        g["_pmid_num"] = pd.to_numeric(g.pmid, errors="coerce")
        g = g.sort_values(["score", "_pmid_num", "pmid"], ascending=[False, True, True], kind="mergesort").reset_index(drop=True)
        g["rank"] = range(1, len(g) + 1)
        rel = g.label_included.astype(int).eq(1)
        n, r = len(g), int(rel.sum())
        relranks = g.loc[rel, "rank"].astype(int).tolist()
        k95, k100 = relranks[math.ceil(.95*r)-1], relranks[-1]
        cumul = rel.cumsum()
        metrics = {"method": method, "review_id": rid, "N": n, "relevant": r, "prevalence": r/n,
            "MAP": float((cumul[rel] / g.loc[rel, "rank"]).mean()),
            "Recall@5%": float(rel.iloc[:max(1,math.ceil(.05*n))].sum()/r),
            "Recall@10%": float(rel.iloc[:max(1,math.ceil(.10*n))].sum()/r),
            "Recall@20%": float(rel.iloc[:max(1,math.ceil(.20*n))].sum()/r),
            "Recall@30%": float(rel.iloc[:max(1,math.ceil(.30*n))].sum()/r),
            "Recall@50%": float(rel.iloc[:max(1,math.ceil(.50*n))].sum()/r),
            "rank_95_recall": k95, "rank_of_last_relevant": k100,
            "WSS@95": 1-k95/n-.05, "WSS@100": 1-k100/n}
        metric_rows.append(metrics)
        ranked.append(g.drop(columns="_pmid_num"))
    return pd.DataFrame(metric_rows), pd.concat(ranked, ignore_index=True)


def create_outputs(questions: dict[str, dict], db: Path, wall_seconds: float, newly_requested: int) -> None:
    judgements = fetch_judgements(db)
    if not judgements.empty and judgements.error.fillna("").ne("").any():
        raise RuntimeError("Some question judgements failed; rerun to resume before evaluating.")
    if not judgements.jev_model.eq(MODEL).all():
        raise RuntimeError(f"All successful calls must return {MODEL}; got {sorted(judgements.jev_model.unique())}")
    base = load_filtered_text()
    expected = sum(len(question_list(questions[rid])) * int(base.review_id.eq(rid).sum()) for rid in REVIEW_IDS)
    if len(judgements) != expected:
        raise RuntimeError(f"Incomplete judgement coverage: got {len(judgements)}, expected {expected}")

    OUT.mkdir(parents=True, exist_ok=True)
    judgements.drop(columns=["error"]).to_csv(OUT/"record_question_judgements.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame([{"review_id":rid,"pmid":pmid,
        "jev_qa_hard_score":float(((g.answer.eq("POSITIVE").astype(float)+.5*g.answer.eq("NEUTRAL").astype(float))).mean()),
        "jev_qa_expected_score":float((g.p_positive+.5*g.p_neutral).mean())}
        for (rid,pmid),g in judgements.groupby(["review_id","pmid"],sort=False)]).to_csv(OUT/"record_qa_scores.csv", index=False, encoding="utf-8-sig")
    wide = pd.read_csv(OUT/"record_qa_scores.csv", dtype={"pmid":str})

    labels = pd.read_csv(BASELINE_SCORES, dtype={"pmid": str})[["review_id", "pmid", "label_included"]]
    holistic_score = pd.read_csv(BASELINE_SCORES, dtype={"pmid":str})[["review_id","pmid","jev_probability"]].rename(columns={"jev_probability":"score"})
    all_reviews, all_ranked = [], []
    for name, score_col, scores in [
        ("Jev-Holistic", "score", holistic_score),
        ("Jev-QA-Hard", "jev_qa_hard_score", wide.rename(columns={"jev_qa_hard_score":"score"})),
        ("Jev-QA-Expected", "jev_qa_expected_score", wide.rename(columns={"jev_qa_expected_score":"score"})),
    ]:
        m, r = evaluate(scores[["review_id","pmid","score"]], labels, name)
        r["method"] = name
        all_reviews.append(m); all_ranked.append(r)
    metrics = pd.concat(all_reviews, ignore_index=True)
    ranked = pd.concat(all_ranked, ignore_index=True)
    metrics.to_csv(OUT/"review_results.csv", index=False)

    # Wide primary comparison and paired differences.
    select = ["N","relevant","WSS@95","WSS@100","MAP"]
    pivot = metrics.pivot(index="review_id",columns="method",values=select)
    comparison = pd.DataFrame(index=REVIEW_IDS)
    comparison.index.name = "review_id"
    for method, short in [("Jev-Holistic","Holistic"),("Jev-QA-Hard","QA_Hard"),("Jev-QA-Expected","QA_Expected")]:
        for metric in select:
            comparison[f"{short}_{metric.replace('@','')}"] = pivot[(metric,method)].reindex(REVIEW_IDS)
    comparison.insert(1,"N",[int(metrics[(metrics.method=="Jev-Holistic")&(metrics.review_id==rid)].N.iloc[0]) for rid in REVIEW_IDS])
    comparison.insert(2,"relevant",[int(metrics[(metrics.method=="Jev-Holistic")&(metrics.review_id==rid)].relevant.iloc[0]) for rid in REVIEW_IDS])
    # Remove duplicated method-specific N/relevant fields while retaining requested leading columns.
    comparison = comparison.loc[:,[c for c in comparison.columns if c in {"N","relevant","Holistic_WSS95","QA_Hard_WSS95","QA_Expected_WSS95","Holistic_WSS100","QA_Hard_WSS100","QA_Expected_WSS100","Holistic_MAP","QA_Hard_MAP","QA_Expected_MAP"}]]
    comparison["QA_Hard_minus_Holistic_WSS95"] = comparison.QA_Hard_WSS95-comparison.Holistic_WSS95
    comparison["QA_Expected_minus_Holistic_WSS95"] = comparison.QA_Expected_WSS95-comparison.Holistic_WSS95
    comparison["QA_Hard_minus_Holistic_WSS100"] = comparison.QA_Hard_WSS100-comparison.Holistic_WSS100
    comparison["QA_Expected_minus_Holistic_WSS100"] = comparison.QA_Expected_WSS100-comparison.Holistic_WSS100
    comparison["QA_Hard_minus_Holistic_MAP"] = comparison.QA_Hard_MAP-comparison.Holistic_MAP
    comparison["QA_Expected_minus_Holistic_MAP"] = comparison.QA_Expected_MAP-comparison.Holistic_MAP
    comparison.reset_index().to_csv(OUT/"aggregate_comparison.csv", index=False)

    # Full metric distribution summaries across the eight topic-level values.
    aggregate=[]
    for (method,metric),g in metrics.melt(id_vars="method",value_vars=["WSS@95","WSS@100","MAP","Recall@5%","Recall@10%","Recall@20%","Recall@30%","Recall@50%"],var_name="metric",value_name="value").groupby(["method","metric"]):
        aggregate.append({"method":method,"metric":metric,"mean":g.value.mean(),"sd":g.value.std(ddof=1),"median":g.value.median(),"min":g.value.min(),"max":g.value.max()})
    pd.DataFrame(aggregate).to_csv(OUT/"aggregate_metrics.csv",index=False)

    # Label-informed text diagnostics are generated only after complete scoring.
    # The judgement table contains model outputs and identifiers only; source
    # title/abstract text stays in the separately loaded, label-free corpus.
    long = judgements[["review_id", "pmid", "question_number", "answer",
                       "p_positive", "p_neutral", "p_negative"]].copy()
    qwide = long.pivot(index=["review_id","pmid"],columns="question_number",values=["answer","p_positive","p_neutral","p_negative"])
    qwide.columns=[f"Q{n}_{stat}" for stat,n in qwide.columns]
    hol_rank=ranked[ranked.method.eq("Jev-Holistic")][["review_id","pmid","score","rank"]].rename(columns={"score":"holistic_score","rank":"holistic_rank"})
    qa_rank=ranked[ranked.method.eq("Jev-QA-Hard")][["review_id","pmid","score","rank"]].rename(columns={"score":"qa_hard_score","rank":"qa_hard_rank"})
    ex_rank=ranked[ranked.method.eq("Jev-QA-Expected")][["review_id","pmid","score","rank"]].rename(columns={"score":"qa_expected_score","rank":"qa_expected_rank"})
    diagnostic=hol_rank.merge(qa_rank,on=["review_id","pmid"]).merge(ex_rank,on=["review_id","pmid"]).merge(labels,on=["review_id","pmid"]).merge(base,on=["review_id","pmid"]).merge(qwide,on=["review_id","pmid"])
    diagnostic=diagnostic.rename(columns={"label_included":"gold_label"})
    diagnostic["rank_difference"]=(diagnostic.holistic_rank-diagnostic.qa_hard_rank).abs()
    substantial={rid:max(10,math.ceil(.05*int(base.review_id.eq(rid).sum()))) for rid in REVIEW_IDS}
    diagnostic=diagnostic[(diagnostic.gold_label.eq(1)) & diagnostic.apply(lambda r:r.rank_difference>=substantial[r.review_id],axis=1)].sort_values(["review_id","rank_difference"],ascending=[True,False])
    diagnostic.to_csv(OUT/"low_scoring_included.csv",index=False,encoding="utf-8-sig")

    # Paired WSS plots show all review pairs and the unweighted cross-review mean.
    for metric,filename in [("WSS@95","wss95_holistic_vs_qa.png"),("WSS@100","wss100_holistic_vs_qa.png")]:
        p=metrics.pivot(index="review_id",columns="method",values=metric).reindex(REVIEW_IDS)
        p.loc["Mean"]=p.mean()
        ax=p.plot(kind="bar",figsize=(12,6),color=["#4472C4","#70AD47","#ED7D31"])
        ax.set_ylabel(metric); ax.set_xlabel("Review (Mean is the unweighted eight-review mean)")
        ax.set_title(f"{metric}: Jev-Holistic vs criterion QA"); ax.grid(axis="y",alpha=.25); ax.legend(title="Method")
        plt.tight_layout(); plt.savefig(OUT/filename,dpi=180); plt.close()

    # Cost/runtime using measured QA work and the already-recorded filtered holistic run.
    total_in=int(pd.to_numeric(judgements.input_tokens,errors="coerce").sum())
    total_out=int(pd.to_numeric(judgements.output_tokens,errors="coerce").sum())
    cost=total_in/1_000_000*INPUT_PRICE_PER_MILLION
    hol_raw=pd.read_csv(BASELINE_SCORES)
    # BASELINE_SCORES is already the abstract-available filtered DTA file.
    hol=hol_raw[hol_raw.error.fillna("").eq("")].copy()
    hol_in=int(pd.to_numeric(hol.input_tokens,errors="coerce").sum())
    hol_out=int(pd.to_numeric(hol.output_tokens,errors="coerce").sum())
    hol_latency=float(pd.to_numeric(hol.latency_seconds,errors="coerce").sum())
    hol_cost=hol_in/1_000_000*INPUT_PRICE_PER_MILLION
    hol_wall=1345.0*(len(hol)/30521) # completed DTA scoring run; proportional filtered-set estimate
    api_errors=int(judgements.error.fillna("").ne("").sum())
    added=cost-hol_cost
    metric_stats=pd.DataFrame(aggregate)
    h95=float(metric_stats[(metric_stats.method=="Jev-Holistic")&(metric_stats.metric=="WSS@95")]["mean"].iloc[0])
    q95=float(metric_stats[(metric_stats.method=="Jev-QA-Hard")&(metric_stats.metric=="WSS@95")]["mean"].iloc[0])
    qe95=float(metric_stats[(metric_stats.method=="Jev-QA-Expected")&(metric_stats.metric=="WSS@95")]["mean"].iloc[0])
    h100=float(metric_stats[(metric_stats.method=="Jev-Holistic")&(metric_stats.metric=="WSS@100")]["mean"].iloc[0])
    q100=float(metric_stats[(metric_stats.method=="Jev-QA-Hard")&(metric_stats.metric=="WSS@100")]["mean"].iloc[0])
    qe100=float(metric_stats[(metric_stats.method=="Jev-QA-Expected")&(metric_stats.metric=="WSS@100")]["mean"].iloc[0])
    hard95_wins=int((comparison.QA_Hard_WSS95>comparison.Holistic_WSS95).sum())
    expected95_wins=int((comparison.QA_Expected_WSS95>comparison.Holistic_WSS95).sum())
    c233=comparison.loc["CD012233"]
    c768=comparison.loc["CD012768"]
    better_hard_95=q95>qe95
    better_hard_100=q100>qe100
    better_hard_map=float(metric_stats[(metric_stats.method=="Jev-QA-Hard")&(metric_stats.metric=="MAP")]["mean"].iloc[0]) > float(metric_stats[(metric_stats.method=="Jev-QA-Expected")&(metric_stats.metric=="MAP")]["mean"].iloc[0])
    md=metrics.pivot(index="review_id",columns="method",values=["WSS@95","WSS@100","MAP"]).reindex(REVIEW_IDS)
    per_lines=[]
    for rid in REVIEW_IDS:
        row=comparison.loc[rid]
        per_lines.append(f"| {rid} | {int(row.N):,} | {int(row.relevant)} | {row.Holistic_WSS95:.4f} | {row.QA_Hard_WSS95:.4f} | {row.QA_Expected_WSS95:.4f} | {row.Holistic_WSS100:.4f} | {row.QA_Hard_WSS100:.4f} | {row.QA_Expected_WSS100:.4f} | {row.Holistic_MAP:.4f} | {row.QA_Hard_MAP:.4f} | {row.QA_Expected_MAP:.4f} |")
    qa_calls=int(len(judgements)); qa_latency=float(pd.to_numeric(judgements.latency_seconds,errors="coerce").sum())
    summary=f"""# Jev-QA-2024 experiment

## Status and design

Jev-QA uses the published Appendix A questions from Akinseloyin et al. (2024), with no edits, on the same filtered abstract-available record set as Jev-Holistic. It does not reproduce their pipeline: this run has no generated answer explanations, BART answer scoring, question-level embedding reranking, or criteria-level embedding reranking. Jev-QA-Expected is a Jev-specific probabilistic variant; QA-Hard is the primary analysis.

The input to each Jev judgement consists of one exact published question and that record's title and abstract. Qrel labels and prior Jev scores are discarded before scoring and joined only after every judgement has completed. Judgements use three-way Choice answers (POSITIVE, NEUTRAL, NEGATIVE) and model `{MODEL}`. No new candidates are retrieved.

Records were ranked by descending score, with ties broken by ascending numeric PMID and then PMID text, matching the existing benchmark. Recall cutoffs use `ceil(p × N)` (minimum one); WSS@95 is `1 - k95/N - 0.05`, where k95 first reaches `ceil(0.95 × relevant)`; WSS@100 is `1 - rank_of_last_relevant/N`. Aggregate values are unweighted across the eight reviews; SD is sample SD.

## Review-level primary comparison

| Review | N | Relevant | Holistic WSS95 | QA-Hard WSS95 | QA-Expected WSS95 | Holistic WSS100 | QA-Hard WSS100 | QA-Expected WSS100 | Holistic MAP | QA-Hard MAP | QA-Expected MAP |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
{chr(10).join(per_lines)}

## Interpretation

- Mean WSS@95: Holistic {h95:.4f}; QA-Hard {q95:.4f} ({q95-h95:+.4f}); QA-Expected {qe95:.4f} ({qe95-h95:+.4f}).
- Mean WSS@100: Holistic {h100:.4f}; QA-Hard {q100:.4f} ({q100-h100:+.4f}); QA-Expected {qe100:.4f} ({qe100-h100:+.4f}).
- QA-Hard improves WSS@95 over Holistic on {hard95_wins}/8 reviews; QA-Expected does so on {expected95_wins}/8. Review-level paired changes are in `aggregate_comparison.csv`.
- CD012233: WSS@95 is {c233.Holistic_WSS95:.4f} Holistic, {c233.QA_Hard_WSS95:.4f} QA-Hard ({c233.QA_Hard_minus_Holistic_WSS95:+.4f}), and {c233.QA_Expected_WSS95:.4f} QA-Expected ({c233.QA_Expected_minus_Holistic_WSS95:+.4f}); WSS@100 changes are {c233.QA_Hard_minus_Holistic_WSS100:+.4f} (Hard) and {c233.QA_Expected_minus_Holistic_WSS100:+.4f} (Expected).
- CD012768: WSS@95 is {c768.Holistic_WSS95:.4f} Holistic, {c768.QA_Hard_WSS95:.4f} QA-Hard ({c768.QA_Hard_minus_Holistic_WSS95:+.4f}), and {c768.QA_Expected_WSS95:.4f} QA-Expected ({c768.QA_Expected_minus_Holistic_WSS95:+.4f}); WSS@100 changes are {c768.QA_Hard_minus_Holistic_WSS100:+.4f} (Hard) and {c768.QA_Expected_minus_Holistic_WSS100:+.4f} (Expected).
- Across mean WSS@95, WSS@100, and MAP, QA-Hard is higher than QA-Expected on {sum([better_hard_95,better_hard_100,better_hard_map])}/3 metrics. QA-Hard remains the prespecified primary score; QA-Expected remains secondary.
- The measured extra cost is ${added:.4f}. Whether the WSS gain justifies that cost depends on the acceptable review-work reduction; the measured gain per dollar is reported below and no method is reclassified as primary based on performance.

## Calls, cost, and runtime

- Review-record pairs: {len(base):,}
- Total question judgements (successful plus failed): {qa_calls:,}
- Input/output tokens: {total_in:,} / {total_out:,}
- Estimated QA cost: ${cost:.4f}; filtered holistic estimated cost: ${hol_cost:.4f}; ratio: {cost/hol_cost if hol_cost else float('nan'):.2f}×.
- WSS@95 gain per additional dollar: QA-Hard ${(q95-h95)/added:.4f}/$; QA-Expected ${(qe95-h95)/added:.4f}/$, where added cost is ${added:.4f}.
- Sum of Jev call latency: {qa_latency:.1f} seconds. Active scoring wall-clock was approximately 5,650 seconds (94 minutes), reconstructed from progress logs across the initial and resumed API runs; the exact combined wall time was not persisted. This excludes the time waiting for credits before resuming.
- Filtered holistic baseline: {hol_latency:.1f} summed call-latency seconds, {hol_wall:.1f}s estimated concurrent wall time, and {hol_in:,}/{hol_out:,} input/output tokens.
- API failures: {api_errors}.
- Holistic wall time is estimated by scaling the recorded concurrent 30,521-call run to the 26,832 filtered pairs; it is not a directly measured filtered-only runtime.
- `low_scoring_included.csv` includes gold-positive records whose Holistic and QA-Hard ranks differ by at least 5% of that review's N (minimum 10 ranks).

## Caveats

This is a retrospective comparison on eight DTA topics. The final-inclusion qrels are evaluation labels, not necessarily original abstract-screening decisions. No conclusions about autonomous exclusion or generalization follow from this benchmark alone. No question, threshold, or parameter was changed based on qrels. Questions are attributed to Akinseloyin et al. 2024 supplementary Appendix A.
"""
    (OUT/"summary.md").write_text(summary,encoding="utf-8")


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers",type=int,default=8)
    parser.add_argument("--questions",type=Path,default=QUESTION_FILE)
    args=parser.parse_args()
    if args.workers<1 or args.workers>32:
        parser.error("--workers must be between 1 and 32")
    if not os.environ.get("TYPESAFE_API_KEY"):
        raise RuntimeError("Set TYPESAFE_API_KEY in the local environment; do not add it to this repository.")
    q=load_questions(args.questions)
    OUT.mkdir(parents=True,exist_ok=True)
    questions_copy=OUT/"questions.json"
    questions_copy.write_text(args.questions.read_text(encoding="utf-8"),encoding="utf-8")
    db=OUT/"jev_qa_judgements.sqlite"
    wall,requested=run_calls(q,args.workers,db)
    saved=fetch_judgements(db)
    records=load_filtered_text()
    expected=sum(len(question_list(q[rid]))*int(records.review_id.eq(rid).sum()) for rid in REVIEW_IDS)
    errors=int(saved.error.fillna("").ne("").sum())
    successful=int((saved.answer.notna() & saved.error.fillna("").eq("")).sum())
    if successful!=expected or errors:
        saved.to_csv(OUT/"record_question_judgements.csv",index=False,encoding="utf-8-sig")
        total_input=int(pd.to_numeric(saved.input_tokens,errors="coerce").sum())
        status={"status":"incomplete",
                "reason":"TypeSafe API credits exhausted" if CREDIT_BLOCKED.is_set() else "question coverage incomplete or API failures remain",
                "expected_question_judgements":expected,"saved_judgement_rows":int(len(saved)),
                "successful_judgements":successful,"rows_with_errors":errors,
                "input_tokens":total_input,"output_tokens":int(pd.to_numeric(saved.output_tokens,errors="coerce").sum()),
                "estimated_cost_usd":total_input/1_000_000*INPUT_PRICE_PER_MILLION,
                "sum_recorded_call_latency_seconds":float(pd.to_numeric(saved.latency_seconds,errors="coerce").sum()),
                "current_process_wall_seconds":wall,"newly_requested_judgements":requested,
                "evaluation_performed":False,"qrels_read":False}
        (OUT/"run_status.json").write_text(json.dumps(status,indent=2)+"\n",encoding="utf-8")
        (OUT/"RUN_STATUS.md").write_text(
            f"# Jev-QA-2024 run status\n\nScoring is incomplete: {successful:,} of {expected:,} question judgments have succeeded, with {errors:,} saved error rows. The provider reported that the organization has no available TypeSafe API credits. No qrels were read and no evaluation was performed. The SQLite checkpoint can be resumed after credits are available.\n",
            encoding="utf-8")
        print(json.dumps(status,indent=2))
        return 2
    # Only now load labels or previous predictions for evaluation/comparison.
    create_outputs(q,db,wall,requested)
    (OUT/"run_status.json").write_text(json.dumps({"status":"complete","expected_question_judgements":expected,
        "successful_judgements":successful,"api_failures":errors,"current_process_wall_seconds":wall,
        "active_scoring_wall_seconds_estimate":5650,"active_scoring_wall_time_is_approximate":True,
        "active_scoring_wall_time_basis":"Progress logs across initial and resumed API sessions; excludes time waiting for credits; exact combined wall time was not persisted.",
        "newly_requested_judgements":requested,"evaluation_performed":True,"qrels_read_after_scoring":True},indent=2)+"\n",encoding="utf-8")
    (OUT/"RUN_STATUS.md").unlink(missing_ok=True)
    print(json.dumps({"output_dir":str(OUT),"judgements":len(fetch_judgements(db)),"scoring_wall_seconds":wall},indent=2))
    return 0


if __name__=="__main__":
    raise SystemExit(main())

