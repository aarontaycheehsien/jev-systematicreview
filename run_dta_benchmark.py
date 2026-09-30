"""Run zero-shot Jev ranking on the eight CLEF-TAR 2019 DTA reviews."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import math
import os
import re
import sqlite3
import sys
import threading
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import requests
from typesafe_sdk import Noul, TypeSafeClient

ROOT = Path(__file__).resolve().parent
SOURCE_ROOT = ROOT / "data" / "clef-tar-source"
PUBMED_CACHE = ROOT / "data" / "pubmed_metadata_cache.json"
INFO_FILE = ROOT / "data" / "dta_criteria" / "info.json"
OUTPUTS = ROOT / "outputs"
DB_FILE = OUTPUTS / "dta_results.sqlite"
RECORD_CSV = OUTPUTS / "dta_record_scores.csv"
REVIEW_CSV = OUTPUTS / "dta_review_results.csv"
LOW_CSV = OUTPUTS / "dta_low_scoring_included.csv"
COMPARISON_CSV = OUTPUTS / "dta_benchmark_comparison.csv"
REVIEW_IDS = ["CD008874", "CD009044", "CD011686", "CD012080", "CD012233", "CD012567", "CD012669", "CD012768"]
CLEF_COMMIT = "dbc13d02bb3e2f8ebc90e62ff47f5eb591e5ca20"
CRITERIA_COMMIT = "49e94170dd0ff9380d8dfefecf8eec4692e8f05d"
TYPE_SAFE_INPUT_PRICE_PER_MILLION = 0.042  # Jev 1.13 price checked 2026-09-21
FIXED_THRESHOLD = 0.50  # carried forward from the prior experiment; no DTA tuning
QUESTION = "Based ONLY on the record's `title` and `abstract` and the review-specific eligibility criteria, should this record be retained for human screening?"
THREAD_LOCAL = threading.local()

def download_sources(force: bool = False) -> None:
    files = []
    for rid in REVIEW_IDS:
        files.append((f"https://raw.githubusercontent.com/CLEF-TAR/tar/{CLEF_COMMIT}/2019-TAR/Task2/Testing/DTA/topics/{rid}", SOURCE_ROOT / "topics" / rid))
    files.append((f"https://raw.githubusercontent.com/CLEF-TAR/tar/{CLEF_COMMIT}/2019-TAR/Task2/Testing/DTA/qrels/full.test.dta.abs.2019.qrels", SOURCE_ROOT / "qrels" / "full.test.dta.abs.2019.qrels"))
    files.append((f"https://raw.githubusercontent.com/XITASO/lgar/{CRITERIA_COMMIT}/implementation/data/tar2019/dta/info.json", INFO_FILE))
    for url, target in files:
        if target.exists() and not force:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        response = requests.get(url, timeout=90)
        response.raise_for_status()
        target.write_bytes(response.content)
    manifest = {
        "clef_tar_repository": "https://github.com/CLEF-TAR/tar",
        "clef_tar_commit": CLEF_COMMIT,
        "qrels_path": "2019-TAR/Task2/Testing/DTA/qrels/full.test.dta.abs.2019.qrels",
        "criteria_repository": "https://github.com/XITASO/lgar",
        "criteria_commit": CRITERIA_COMMIT,
        "criteria_path": "implementation/data/tar2019/dta/info.json",
        "pmid_metadata_source": "NCBI PubMed E-utilities efetch.fcgi",
    }
    (ROOT / "data" / "dta_source_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def load_topics_and_qrels():
    qrels = {rid: {} for rid in REVIEW_IDS}
    qrel_path = SOURCE_ROOT / "qrels" / "full.test.dta.abs.2019.qrels"
    for line_no, line in enumerate(qrel_path.read_text(encoding="utf-8-sig", errors="replace").splitlines(), 1):
        parts = line.split()
        if not parts or parts[0] not in qrels:
            continue
        if len(parts) < 4:
            raise ValueError(f"Bad qrel row {line_no}: {line!r}")
        rid, pmid, grade = parts[0], parts[2], int(parts[3])
        if pmid in qrels[rid]:
            raise ValueError(f"Duplicate qrel PMID {rid}/{pmid}")
        qrels[rid][pmid] = int(grade > 0)

    topics = {}
    for rid in REVIEW_IDS:
        text = (SOURCE_ROOT / "topics" / rid).read_text(encoding="utf-8-sig", errors="replace")
        # The official topic format labels its final candidate-ID section "Pids:".
        pmid_section = re.split(r"(?im)^Pids:\s*$", text)[-1]
        pmids = re.findall(r"^\s*(\d{4,10})\s*$", pmid_section, re.M)
        if len(pmids) != len(set(pmids)):
            raise ValueError(f"Duplicate topic PMIDs in {rid}")
        topics[rid] = pmids
        topic_set, qrel_set = set(pmids), set(qrels[rid])
        if topic_set != qrel_set:
            raise ValueError(f"Candidate/qrel mismatch for {rid}: missing qrels={len(topic_set-qrel_set)}, extra qrels={len(qrel_set-topic_set)}")
    return topics, qrels


def pubmed_xml_records(xml_bytes: bytes) -> dict[str, dict]:
    root = ET.fromstring(xml_bytes)
    out = {}
    for article in root.findall(".//PubmedArticle"):
        citation = article.find("MedlineCitation")
        article_data = citation.find("Article") if citation is not None else None
        if citation is None or article_data is None:
            continue
        pmid_node = citation.find("PMID")
        if pmid_node is None or not pmid_node.text:
            continue
        title_node = article_data.find("ArticleTitle")
        title = " ".join("".join(title_node.itertext()).split()) if title_node is not None else ""
        abstract_node = article_data.find("Abstract")
        chunks = []
        if abstract_node is not None:
            for item in abstract_node.findall("AbstractText"):
                value = " ".join("".join(item.itertext()).split())
                if value:
                    label = item.attrib.get("Label") or item.attrib.get("NlmCategory")
                    chunks.append(f"{label}: {value}" if label else value)
        out[pmid_node.text.strip()] = {"title": title, "abstract": " ".join(chunks), "retrieval_error": ""}
    return out


def retrieve_pubmed(pmids: list[str], batch_size: int = 150, delay: float = 0.35) -> dict[str, dict]:
    if PUBMED_CACHE.exists():
        cache = json.loads(PUBMED_CACHE.read_text(encoding="utf-8"))
    else:
        cache = {}
    missing = [pmid for pmid in pmids if pmid not in cache]
    print(f"PubMed cache: {len(pmids)-len(missing)} cached; retrieving {len(missing)}", flush=True)
    for start in range(0, len(missing), batch_size):
        batch = missing[start:start + batch_size]
        params = {"db": "pubmed", "id": ",".join(batch), "retmode": "xml", "tool": "jev_dta_screening_benchmark"}
        email = os.environ.get("NCBI_EMAIL")
        if email:
            params["email"] = email
        if os.environ.get("NCBI_API_KEY"):
            params["api_key"] = os.environ["NCBI_API_KEY"]
        error = ""
        for attempt in range(5):
            try:
                response = requests.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi", params=params, timeout=90)
                response.raise_for_status()
                parsed = pubmed_xml_records(response.content)
                cache.update(parsed)
                not_returned = set(batch) - set(parsed)
                for pmid in not_returned:
                    cache[pmid] = {"title": "", "abstract": "", "retrieval_error": "PMID not returned by PubMed EFetch"}
                error = ""
                break
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                time.sleep(min(2**attempt, 16))
        if error:
            for pmid in batch:
                cache[pmid] = {"title": "", "abstract": "", "retrieval_error": error}
        # Persist after each response batch so a restart does not repeat PubMed retrieval.
        PUBMED_CACHE.parent.mkdir(parents=True, exist_ok=True)
        PUBMED_CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
        count = min(start + batch_size, len(missing))
        print(f"PubMed metadata retrieved/cached: {len(pmids)-len(missing)+count}/{len(pmids)}", flush=True)
        time.sleep(delay)
    return cache


def criteria_for(info: dict, rid: str) -> dict:
    item = info[rid]
    return {key: item.get(key, "") for key in ("title", "inclusion_criteria", "exclusion_criteria", "research_questions", "objectives", "link")}


def init_db() -> None:
    OUTPUTS.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS scores (
            review_id TEXT NOT NULL, pmid TEXT NOT NULL, title TEXT, abstract TEXT,
            label_included INTEGER NOT NULL, jev_probability REAL, jev_model TEXT,
            input_tokens INTEGER, output_tokens INTEGER, latency_seconds REAL,
            error TEXT, PRIMARY KEY (review_id, pmid))""")


def saved_successes() -> set[tuple[str, str]]:
    with sqlite3.connect(DB_FILE) as conn:
        rows = conn.execute("SELECT review_id, pmid FROM scores WHERE error IS NULL OR error = ''").fetchall()
    return set(rows)


def request_state(record: dict) -> dict[str, str]:
    """Return only the candidate record text as Jev's structured state."""
    return {
        "title": record["title"] or "[TITLE UNAVAILABLE]",
        "abstract": record["abstract"] or "[ABSTRACT UNAVAILABLE]",
    }


def make_retain_question(review: dict) -> Noul:
    """Keep review eligibility logic in the question, separate from record state."""
    instructions = (
        f"Review title: {review['title']}\n"
        f"Research question: {review['research_questions']}\n"
        f"Review objectives: {review['objectives']}\n"
        f"Inclusion criteria:\n{review['inclusion_criteria']}\n"
        f"Exclusion criteria:\n{review['exclusion_criteria']}\n\n"
        f"{QUESTION} "
        "Retain when it meets or may plausibly meet the inclusion criteria and does not "
        "clearly meet an exclusion criterion. If the title or abstract is insufficient "
        "to exclude confidently, retain it."
    )
    return Noul(instructions=instructions, criteria={
        "true": "Retain for human screening; the record meets or may plausibly meet the review's inclusion criteria and does not clearly meet an exclusion criterion.",
        "false": "Confidently exclude; the title and abstract clearly show that the record fails an inclusion criterion or meets an exclusion criterion.",
    })


def open_client() -> TypeSafeClient:
    if not hasattr(THREAD_LOCAL, "client"):
        THREAD_LOCAL.client = TypeSafeClient()
    return THREAD_LOCAL.client


def score_one(record: dict) -> dict:
    client = open_client()
    review = record["criteria"]
    state = request_state(record)
    question = make_retain_question(review)
    last = None
    for attempt in range(4):
        start = time.perf_counter()
        try:
            response = client.system_one(state=state, questions={"retain": question})
            latency = time.perf_counter() - start
            p = float(response.answers["retain"].noul)
            if not 0 <= p <= 1:
                raise ValueError(f"Invalid probability: {p}")
            return {"review_id": record["review_id"], "pmid": record["pmid"], "title": record["title"], "abstract": record["abstract"], "label_included": record["label_included"],
                    "jev_probability": p, "jev_model": response.model, "input_tokens": response.usage.input_tokens, "output_tokens": response.usage.output_tokens, "latency_seconds": latency, "error": ""}
        except Exception as exc:
            last = exc
            if attempt < 3:
                time.sleep(2**attempt)
    return {"review_id": record["review_id"], "pmid": record["pmid"], "title": record["title"], "abstract": record["abstract"], "label_included": record["label_included"],
            "jev_probability": None, "jev_model": "", "input_tokens": None, "output_tokens": None, "latency_seconds": None, "error": f"{type(last).__name__}: {last}"}


def write_batch(batch: list[dict]) -> None:
    # Article text lives in the shared PubMed cache; don't duplicate it in the
    # resume database. This keeps checkpoints small while retaining scores.
    compact_batch = [{**row, "title": "", "abstract": ""} for row in batch]
    with sqlite3.connect(DB_FILE) as conn:
        conn.executemany("""INSERT OR REPLACE INTO scores
        (review_id,pmid,title,abstract,label_included,jev_probability,jev_model,input_tokens,output_tokens,latency_seconds,error)
        VALUES (:review_id,:pmid,:title,:abstract,:label_included,:jev_probability,:jev_model,:input_tokens,:output_tokens,:latency_seconds,:error)""", compact_batch)


def export_record_csv() -> pd.DataFrame:
    with sqlite3.connect(DB_FILE) as conn:
        df = pd.read_sql_query("""SELECT review_id,pmid,label_included,jev_probability,jev_model,
        input_tokens,output_tokens,latency_seconds,error FROM scores
        ORDER BY review_id, CAST(pmid AS INTEGER)""", conn)
    df.to_csv(RECORD_CSV, index=False, encoding="utf-8-sig")
    return df


def metrics_for_review(df: pd.DataFrame) -> dict:
    rid = df.review_id.iloc[0]
    df = df.copy()
    df["_pmid_int"] = pd.to_numeric(df.pmid, errors="coerce")
    df = df.sort_values(["jev_probability", "_pmid_int", "pmid"], ascending=[False, True, True], kind="mergesort").reset_index(drop=True)
    df["rank"] = range(1, len(df) + 1)
    relevant = df.label_included.astype(int).eq(1)
    n, r = len(df), int(relevant.sum())
    last_rel = int(df.loc[relevant, "rank"].max()) if r else None
    k95 = int(df.loc[relevant, "rank"].sort_values().iloc[max(0, math.ceil(.95 * r) - 1)]) if r else None
    k100 = last_rel
    precision_at_rel = (relevant.cumsum()[relevant] / df.loc[relevant, "rank"]).sum() / r if r else float("nan")
    result = {"review_id": rid, "total_records": n, "number_relevant": r, "prevalence": r / n if n else float("nan"), "MAP": float(precision_at_rel),
              "Recall@5%": float(relevant.iloc[:max(1, math.ceil(.05*n))].sum()/r) if r else float("nan"),
              "Recall@10%": float(relevant.iloc[:max(1, math.ceil(.10*n))].sum()/r) if r else float("nan"),
              "Recall@20%": float(relevant.iloc[:max(1, math.ceil(.20*n))].sum()/r) if r else float("nan"),
              "Recall@50%": float(relevant.iloc[:max(1, math.ceil(.50*n))].sum()/r) if r else float("nan"),
              "rank_95_recall": k95, "records_screened_to_95": k95, "workload_reduction_at_95": 1-k95/n if n and k95 else float("nan"),
              "WSS@95": 1-k95/n-.05 if n and k95 else float("nan"), "WSS@100": 1-k100/n if n and k100 else float("nan"), "rank_of_last_relevant": last_rel,
              "Jev latency seconds": float(pd.to_numeric(df.latency_seconds, errors="coerce").sum()),
              "input_tokens": int(pd.to_numeric(df.input_tokens, errors="coerce").sum()), "output_tokens": int(pd.to_numeric(df.output_tokens, errors="coerce").sum()),
              "api_errors": int(df.error.fillna("").ne("").sum()), "missing_abstracts": int(df.abstract.fillna("").str.strip().eq("").sum()),
              "fixed_0.50_recall": float(((df.jev_probability >= FIXED_THRESHOLD) & relevant).sum()/r) if r else float("nan"),
              "fixed_0.50_retained": int((df.jev_probability >= FIXED_THRESHOLD).sum()),
              "fixed_0.50_workload_reduction": float((df.jev_probability < FIXED_THRESHOLD).sum()/n) if n else float("nan"),
              "post_hoc_oracle_100_threshold": float(df.loc[relevant,"jev_probability"].min()) if r else float("nan")}
    return result, df


def make_outputs(records: pd.DataFrame, qrels: dict[str, dict], criteria_info: dict, pubmed_cache: dict) -> None:
    OUTPUTS.mkdir(parents=True, exist_ok=True)
    results = []
    ranked_by_review = {}
    criteria_used = {rid: criteria_for(criteria_info, rid) for rid in REVIEW_IDS}
    for rid in REVIEW_IDS:
        subset = records[(records.review_id == rid) & records.error.fillna("").eq("") & records.jev_probability.notna()].copy()
        if subset.empty:
            continue
        metric, ranked = metrics_for_review(subset)
        metric["candidate_records"] = len(qrels[rid])
        metric["pubmed_retrieval_failures"] = sum(bool(pubmed_cache.get(pmid, {}).get("retrieval_error")) for pmid in qrels[rid])
        results.append(metric)
        ranked_by_review[rid] = ranked
    review_df = pd.DataFrame(results)
    review_df.to_csv(REVIEW_CSV, index=False, encoding="utf-8-sig")
    (OUTPUTS / "dta_criteria_used.json").write_text(json.dumps(criteria_used, ensure_ascii=False, indent=2), encoding="utf-8")

    low = []
    for rid, ranked in ranked_by_review.items():
        info = criteria_used[rid]
        r = int(ranked.label_included.sum())
        cumulative_relevant = ranked.label_included.cumsum()
        k95 = int(cumulative_relevant.ge(.95*r).idxmax()+1) if r else len(ranked)
        for row in ranked[(ranked.label_included == 1) & ((ranked["rank"] > k95) | (ranked.jev_probability < FIXED_THRESHOLD))].itertuples(index=False):
            low.append({"review_id": rid, "pmid": row.pmid, "title": row.title, "abstract": row.abstract, "jev_probability": row.jev_probability, "rank": row.rank,
                        "percentile_rank_from_top": 100*(row.rank-1)/max(1,len(ranked)-1), "rank95_cutoff": k95,
                        "relevant_criterion_for_manual_inspection": info["inclusion_criteria"],
                        "flag_reason": "rank below the point needed for 95% recall" if row.rank > k95 else "Jev probability below carried-forward fixed threshold 0.50"})
    pd.DataFrame(low, columns=["review_id","pmid","title","abstract","jev_probability","rank","percentile_rank_from_top","rank95_cutoff","relevant_criterion_for_manual_inspection","flag_reason"]).to_csv(LOW_CSV,index=False,encoding="utf-8-sig")

    all_primary = ["WSS@95", "WSS@100", "MAP", "Recall@5%", "Recall@10%", "Recall@20%", "Recall@50%"]
    means = review_df[all_primary].mean(numeric_only=True)
    sds = review_df[all_primary].std(ddof=1, numeric_only=True)
    comparison = pd.DataFrame([
        {"system":"Akinseloyin 2024, Claude 3 QA + Gemini text-embedding-004 reranking", "setting":"zero-shot QA and embedding reranking", "mean_dta_wss95":.653,"sd_dta_wss95":None,"mean_dta_wss100":.573,"sd_dta_wss100":None,"source":"https://academic.oup.com/jamia/article/31/9/1939/7718667"},
        {"system":"Akinseloyin 2026, Soft-Vote", "setting":"zero-shot multi-LLM", "mean_dta_wss95":.680,"sd_dta_wss95":.228,"mean_dta_wss100":.667,"sd_dta_wss100":.266,"source":"https://academic.oup.com/biomethods/article/11/1/bpag006/8460762"},
        {"system":"Jev", "setting":"zero-shot single judgement model", "mean_dta_wss95":means.get("WSS@95"),"sd_dta_wss95":sds.get("WSS@95"),"mean_dta_wss100":means.get("WSS@100"),"sd_dta_wss100":sds.get("WSS@100"),"source":"This experiment"},
    ])
    comparison.to_csv(COMPARISON_CSV,index=False)

    if not review_df.empty:
        fig, ax = plt.subplots(figsize=(10,5.5))
        plot_df = review_df[["review_id","WSS@95"]].copy()
        plot_df.loc[len(plot_df)] = ["Mean", float(means["WSS@95"])]
        colors = ["#4472C4"]*len(review_df)+["#E07A2D"]
        ax.bar(plot_df.review_id,plot_df["WSS@95"],color=colors)
        ax.axhline(float(means["WSS@95"]),color="#E07A2D",linestyle="--",linewidth=1)
        ax.set(ylabel="WSS@95",xlabel="CLEF-TAR 2019 DTA review",title="Jev ranking efficiency by review")
        ax.grid(axis="y",alpha=.25); fig.tight_layout(); fig.savefig(OUTPUTS/"wss95_by_review.png",dpi=160); plt.close(fig)

        fig, axes = plt.subplots(2,4,figsize=(15,8),sharey=True)
        for ax,rid in zip(axes.flat, REVIEW_IDS):
            ranked=ranked_by_review.get(rid)
            if ranked is not None:
                ax.plot(ranked["rank"]/len(ranked)*100,ranked.label_included.cumsum()/ranked.label_included.sum()*100,color="#4472C4")
            ax.axhline(95,color="#E07A2D",linestyle="--",linewidth=1)
            ax.set_title(rid); ax.set_xlabel("Records screened (%)"); ax.grid(alpha=.2)
        axes[0,0].set_ylabel("Relevant studies found (%)"); axes[1,0].set_ylabel("Relevant studies found (%)")
        fig.suptitle("Cumulative recall along Jev's ranking"); fig.tight_layout(); fig.savefig(OUTPUTS/"recall_curves.png",dpi=160); plt.close(fig)

    errors = int(records.error.fillna("").ne("").sum())
    retrieval_failures = sum(bool(pubmed_cache.get(pmid, {}).get("retrieval_error")) for rid in REVIEW_IDS for pmid in qrels[rid])
    total_in = int(pd.to_numeric(records.input_tokens,errors="coerce").sum())
    total_out = int(pd.to_numeric(records.output_tokens,errors="coerce").sum())
    cost = total_in/1_000_000*TYPE_SAFE_INPUT_PRICE_PER_MILLION
    model_set = ", ".join(sorted(records.jev_model.dropna().unique()))
    run_meta_path = OUTPUTS / "dta_run_metadata.json"
    run_metadata = json.loads(run_meta_path.read_text(encoding="utf-8")) if run_meta_path.exists() else {}
    scoring_wall_seconds = run_metadata.get("scoring_wall_seconds")
    wall_text = f"about {scoring_wall_seconds/60:.1f} minutes" if scoring_wall_seconds is not None else "not recorded"
    all_complete = len(review_df)==len(REVIEW_IDS) and all(
        int(row.total_records) == int(row.candidate_records) and int(row.api_errors) == 0 and int(row.pubmed_retrieval_failures) == 0
        for _, row in review_df.iterrows()
    )
    if all_complete:
        agg=lambda c: f"{means[c]:.3f} (SD {sds[c]:.3f}; median {review_df[c].median():.3f}; range {review_df[c].min():.3f}–{review_df[c].max():.3f})"
        worst = review_df.sort_values("WSS@95").iloc[0]
        best = review_df.sort_values("WSS@95").iloc[-1]
        agg_text="\n".join(f"- {c}: {agg(c)}" for c in all_primary)
        per_review="\n".join(f"- {r.review_id}: WSS@95 {r['WSS@95']:.3f}; WSS@100 {r['WSS@100']:.3f}; MAP {r.MAP:.3f}; R@5/10/20/50 {r['Recall@5%']:.1%}/{r['Recall@10%']:.1%}/{r['Recall@20%']:.1%}/{r['Recall@50%']:.1%}; n={int(r.total_records)}, relevant={int(r.number_relevant)}" for _,r in review_df.iterrows())
        report_result=f"Mean WSS@95 was {means['WSS@95']:.3f} (SD {sds['WSS@95']:.3f}; median {review_df['WSS@95'].median():.3f}; range {review_df['WSS@95'].min():.3f}–{review_df['WSS@95'].max():.3f})."
        comparison_text=f"Jev's mean differs from 2024's 0.653 by {means['WSS@95']-.653:+.3f} and from 2026 Soft-Vote's 0.680 by {means['WSS@95']-.680:+.3f}. These are descriptive comparisons, not head-to-head tests. Performance was lowest on {worst.review_id} (WSS@95 {worst['WSS@95']:.3f}) and highest on {best.review_id} (WSS@95 {best['WSS@95']:.3f})."
    else:
        agg_text="Not calculated because not all eight reviews have complete Jev scores."
        per_review="\n".join(f"- {r.review_id}: available records={int(r.total_records)}, relevant={int(r.number_relevant)}, API errors={int(r.api_errors)}" for _,r in review_df.iterrows())
        report_result=f"Incomplete run: {len(review_df)} of 8 review metrics available."
        comparison_text="No aggregate comparison is reported until all eight reviews are complete."
    missing_abstracts=int(records.abstract.fillna("").str.strip().eq("").sum())
    positive_pairs=sum(sum(labels.values()) for labels in qrels.values())
    unique_pmids=len(set(pmid for labels in qrels.values() for pmid in labels))
    fixed_recall_mean=review_df["fixed_0.50_recall"].mean() if not review_df.empty else float("nan")
    fixed_workload_mean=review_df["fixed_0.50_workload_reduction"].mean() if not review_df.empty else float("nan")
    fixed_recall_min=review_df["fixed_0.50_recall"].min() if not review_df.empty else float("nan")
    fixed_recall_max=review_df["fixed_0.50_recall"].max() if not review_df.empty else float("nan")
    summary=f"""# Jev on CLEF-TAR 2019 DTA reviews

## Dataset and validation

- Source set: official CLEF-TAR 2019 Task 2 Testing DTA PMID lists and `full.test.dta.abs.2019.qrels`; PubMed title/abstract metadata fetched with NCBI E-utilities and cached locally.
- Reviews: {len(REVIEW_IDS)} requested topics. Candidate PMID and qrel sets matched exactly before scoring ({len(records):,} review-record pairs, {unique_pmids:,} distinct PMIDs, and {positive_pairs} relevant qrel labels; per-review counts are in the result table).
- Criteria: review-specific inclusion/exclusion criteria, questions, objectives and title copied to `dta_criteria_used.json`.
- PubMed records not retrieved: {retrieval_failures}; missing abstracts among processed review-record pairs: {missing_abstracts} ({int(records.abstract.fillna('').str.strip().eq('').groupby(records.pmid).max().sum())} distinct PMIDs).
- Successful Jev scores: {int(records.jev_probability.notna().sum())}; API failures: {errors}; returned model(s): {model_set or 'none'}.
- Gold qrels are evaluation-only and are not in the Jev state or question. No examples, tuning, or DTA label feedback were used.
- Ties are ordered deterministically by numeric PMID ascending after descending Jev retain probability.
- Recall@k uses the first `ceil(k × N)` records (minimum one). WSS@95 uses the first rank where cumulative positives reach at least 95% of the qrel positives, then `1 - rank/N - 0.05`. WSS@100 is `1 - last_relevant_rank/N`.

## Primary results

{report_result}

Aggregate metrics (arithmetic mean across review-level values; SD is sample standard deviation):

{agg_text}

### Per review

{per_review}

## Published comparison

{comparison_text}

| System | Setting | Mean DTA WSS@95 (SD) | Mean DTA WSS@100 (SD) |
|---|---|---:|---:|
| Akinseloyin 2024, Claude 3 QA + Gemini embedding reranking | zero-shot | 0.653 (not reported) | 0.573 (not reported) |
| Akinseloyin 2026, Soft-Vote | zero-shot multi-LLM | 0.680 (0.228) | 0.667 (0.266) |
| Jev | zero-shot single judgement model | {means.get('WSS@95',float('nan')):.3f} ({sds.get('WSS@95',float('nan')):.3f}) | {means.get('WSS@100',float('nan')):.3f} ({sds.get('WSS@100',float('nan')):.3f}) |

The comparison is not head-to-head. The [2024 system](https://academic.oup.com/jamia/article/31/9/1939/7718667) converted criteria into question-answering tasks and re-ranked with embeddings; the [2026 Soft-Vote system](https://academic.oup.com/biomethods/article/11/1/bpag006/8460762) combines multiple LLM outputs; Jev uses one bounded judgment per record without review-specific training. Differences in model, prompt construction, ranking and implementation matter, so screening performance should be considered alongside model and computational complexity.

## Carried-forward fixed threshold (secondary)

Threshold 0.50 is carried forward from the earlier Jev experiment without using DTA labels to alter it. Per-review recall and workload reduction are in `dta_review_results.csv`. This threshold was not prospectively validated as universal. Any `post_hoc_oracle_100_threshold` values in that file are label-informed descriptions only.

Across the eight reviews, fixed-threshold recall averaged {fixed_recall_mean:.1%} (range {fixed_recall_min:.1%}–{fixed_recall_max:.1%}) and workload reduction averaged {fixed_workload_mean:.1%}. The wide recall range shows that the earlier probability threshold does not transfer consistently across these criteria sets.

## Difficult relevant records

`dta_low_scoring_included.csv` lists every relevant record below the rank needed for 95% recall or below the carried-forward 0.50 threshold. The criteria field supplies review eligibility language for manual inspection; it does not assert why Jev scored a record poorly. Missing eligibility characteristics in abstracts should be assessed from the records themselves.

## Runtime and API use

- Total input tokens: {total_in:,}; output tokens: {total_out:,}.
- Approximate Jev inference cost: ${cost:.4f}, calculated at $0.042 per million input tokens for Jev 1.13 ([price checked 2026-09-21](https://www.typesafeai.org/guides/jev-pricing)); output tokens are free. Provider account billing is authoritative.
- Jev scoring wall time: {wall_text}.
- Sum of recorded call latencies: {pd.to_numeric(records.latency_seconds,errors='coerce').sum():.1f} seconds across concurrent requests (not wall time).

## Interpretation

{report_result} {comparison_text} These eight retrospective DTA topics do not establish that Jev is safe for autonomous review screening or that results generalize to other review types. CLEF qrels define this benchmark's relevance labels; they are used only after scoring to evaluate the fixed ranking.
"""
    (OUTPUTS/"dta_summary.md").write_text(summary,encoding="utf-8")


def main() -> int:
    global OUTPUTS, DB_FILE, RECORD_CSV, REVIEW_CSV, LOW_CSV, COMPARISON_CSV
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh-source",action="store_true",help="redownload pinned CLEF/criteria source files")
    parser.add_argument("--workers",type=int,default=8)
    parser.add_argument("--output-dir",type=Path,default=OUTPUTS,help="directory for this run's scores and reports")
    parser.add_argument("--validate-only",action="store_true",help="download/cache data and validate without Jev API calls")
    args=parser.parse_args()
    if args.workers<1 or args.workers>32:
        parser.error("--workers must be between 1 and 32")
    OUTPUTS=args.output_dir.resolve()
    DB_FILE=OUTPUTS/"dta_results.sqlite"
    RECORD_CSV=OUTPUTS/"dta_record_scores.csv"
    REVIEW_CSV=OUTPUTS/"dta_review_results.csv"
    LOW_CSV=OUTPUTS/"dta_low_scoring_included.csv"
    COMPARISON_CSV=OUTPUTS/"dta_benchmark_comparison.csv"
    download_sources(force=args.refresh_source)
    topics,qrels=load_topics_and_qrels()
    info=json.loads(INFO_FILE.read_text(encoding="utf-8"))
    missing_info=set(REVIEW_IDS)-set(info)
    if missing_info: raise ValueError(f"Missing criteria for: {sorted(missing_info)}")
    all_pmids=list(dict.fromkeys(p for rid in REVIEW_IDS for p in topics[rid]))
    cache=retrieve_pubmed(all_pmids)
    total=0
    for rid in REVIEW_IDS:
        n=len(topics[rid]); positives=sum(qrels[rid].values())
        total+=n
        print(f"VALID {rid}: PMIDs={n}; qrels={len(qrels[rid])}; relevant={positives}; PubMed returned={sum(not cache.get(p,{}).get('retrieval_error') for p in topics[rid])}",flush=True)
    print(f"VALID total candidate records={total}; topic/qrel mapping is exact.",flush=True)
    if args.validate_only:
        return 0
    if not os.environ.get("TYPESAFE_API_KEY"):
        raise RuntimeError("Set TYPESAFE_API_KEY before the Jev scoring run.")
    init_db()
    existing=saved_successes()
    work=[]
    for rid in REVIEW_IDS:
        criterion=criteria_for(info,rid)
        for pmid in topics[rid]:
            if (rid,pmid) in existing:
                continue
            metadata=cache.get(pmid,{"title":"","abstract":"","retrieval_error":"PMID absent from cache"})
            label=qrels[rid][pmid]
            if metadata.get("retrieval_error"):
                work.append({"review_id":rid,"pmid":pmid,"title":metadata.get("title",""),"abstract":metadata.get("abstract",""),"label_included":label,
                             "jev_probability":None,"jev_model":"","input_tokens":None,"output_tokens":None,"latency_seconds":None,"error":"PubMed retrieval: "+metadata["retrieval_error"]})
            else:
                work.append({"review_id":rid,"pmid":pmid,"title":metadata.get("title",""),"abstract":metadata.get("abstract",""),"label_included":label,"criteria":criterion})
    failed_pubmed=[r for r in work if "criteria" not in r]
    if failed_pubmed:
        write_batch(failed_pubmed)
        work=[r for r in work if "criteria" in r]
    print(f"Jev scores already cached: {len(existing)}; new API decisions: {len(work)}; workers={args.workers}",flush=True)
    scoring_wall_seconds = None
    if work:
        completed=[]
        start=time.perf_counter()
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures=[pool.submit(score_one,record) for record in work]
            for future in concurrent.futures.as_completed(futures):
                completed.append(future.result())
                if len(completed)>=50:
                    write_batch(completed); completed.clear()
                    current=export_record_csv()
                    done=int(current.jev_probability.notna().sum())
                    print(f"Jev scored {done}/{total}; elapsed {time.perf_counter()-start:.0f}s",flush=True)
            if completed:
                write_batch(completed)
        scoring_wall_seconds=time.perf_counter()-start
        export_record_csv()
    records=export_record_csv()
    records["title"] = records.pmid.astype(str).map(lambda pmid: cache.get(pmid, {}).get("title", ""))
    records["abstract"] = records.pmid.astype(str).map(lambda pmid: cache.get(pmid, {}).get("abstract", ""))
    # Ensure one output row per candidate PMID even where retrieval/API errors occurred.
    expected={(rid,pmid) for rid in REVIEW_IDS for pmid in topics[rid]}
    actual=set(zip(records.review_id,records.pmid.astype(str)))
    if expected != actual:
        raise ValueError(f"Output coverage mismatch: missing={len(expected-actual)}, unexpected={len(actual-expected)}")
    if scoring_wall_seconds is not None:
        (OUTPUTS/"dta_run_metadata.json").write_text(json.dumps({"scoring_wall_seconds":scoring_wall_seconds,"workers":args.workers,"score_rows":len(records),"recorded_utc_finished":time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())},indent=2),encoding="utf-8")
    (OUTPUTS/"dta_criteria_used.json").write_text(json.dumps({rid:criteria_for(info,rid) for rid in REVIEW_IDS},ensure_ascii=False,indent=2),encoding="utf-8")
    make_outputs(records,qrels,info,cache)
    print(f"Complete. Scored rows: {int(records.jev_probability.notna().sum())}; errors: {int(records.error.fillna('').ne('').sum())}. Outputs in {OUTPUTS}",flush=True)
    return 0


if __name__=="__main__":
    sys.exit(main())
