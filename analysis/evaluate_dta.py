from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd

REVIEW_IDS = ['CD008874', 'CD009044', 'CD011686', 'CD012080', 'CD012233', 'CD012567', 'CD012669', 'CD012768']
FIXED_THRESHOLD = 0.50


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def evaluate_review(data: pd.DataFrame, review_id: str):
    d = data.loc[data.review_id.eq(review_id)].copy()
    d['_pmid_numeric'] = pd.to_numeric(d.pmid, errors='coerce')
    d = d.sort_values(
        ['jev_probability', '_pmid_numeric', 'pmid'],
        ascending=[False, True, True], kind='mergesort'
    ).reset_index(drop=True)
    d['rank'] = range(1, len(d) + 1)
    d['percentile_rank_from_top'] = 100 * (d['rank'] - 1) / max(1, len(d) - 1)
    relevant = d.label_included.astype(int).eq(1)
    n, positives = len(d), int(relevant.sum())
    if not n or not positives:
        raise ValueError(f'{review_id}: expected non-empty review and at least one positive')
    rel_ranks = d.loc[relevant, 'rank'].astype(int).sort_values().tolist()
    k95 = rel_ranks[math.ceil(.95 * positives) - 1]
    k100 = rel_ranks[-1]
    cumulative = relevant.cumsum()
    values = {
        'review_id': review_id,
        'total_records': n,
        'number_relevant': positives,
        'prevalence': positives / n,
        'MAP': float((cumulative[relevant] / d.loc[relevant, 'rank']).mean()),
        'Recall@5%': float(relevant.iloc[:max(1, math.ceil(.05*n))].sum() / positives),
        'Recall@10%': float(relevant.iloc[:max(1, math.ceil(.10*n))].sum() / positives),
        'Recall@20%': float(relevant.iloc[:max(1, math.ceil(.20*n))].sum() / positives),
        'Recall@50%': float(relevant.iloc[:max(1, math.ceil(.50*n))].sum() / positives),
        'rank_95_recall': k95,
        'records_screened_to_95': k95,
        'workload_reduction_at_95': 1 - k95/n,
        'WSS@95': 1 - k95/n - .05,
        'rank_of_last_relevant': k100,
        'WSS@100': 1 - k100/n,
        'fixed_0.50_recall': float(((d.jev_probability >= FIXED_THRESHOLD) & relevant).sum()/positives),
        'fixed_0.50_retained': int((d.jev_probability >= FIXED_THRESHOLD).sum()),
        'fixed_0.50_workload_reduction': float((d.jev_probability < FIXED_THRESHOLD).sum()/n),
        'post_hoc_oracle_100_threshold': float(d.loc[relevant, 'jev_probability'].min()),
    }
    return values, d.drop(columns=['_pmid_numeric'])


def main():
    repo = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description='Offline evaluation of saved CLEF-TAR Jev scores.')
    parser.add_argument('--input', type=Path, default=repo/'data'/'jev_dta_scores.csv')
    parser.add_argument('--output-dir', type=Path, default=repo/'results'/'filtered_abstracts')
    args = parser.parse_args()
    source = args.input.resolve()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    try:
        display_source = source.relative_to(repo).as_posix()
    except ValueError:
        display_source = args.input.as_posix()

    raw = pd.read_csv(source, dtype={'pmid': str})
    required = {'review_id','pmid','label_included','jev_probability','jev_model','abstract_available'}
    missing_columns = required - set(raw.columns)
    if missing_columns:
        raise ValueError(f'Missing required columns: {sorted(missing_columns)}')
    raw['abstract_available'] = raw['abstract_available'].astype(str).str.lower().map({'true':True,'false':False,'1':True,'0':False})
    if raw.abstract_available.isna().any():
        raise ValueError('abstract_available must contain only true/false values')
    if raw.jev_probability.isna().any() or not raw.jev_probability.between(0, 1).all():
        raise ValueError('Every Jev probability must be present and between 0 and 1')
    if raw.label_included.isna().any() or not raw.label_included.isin([0,1]).all():
        raise ValueError('label_included must contain only 0/1')
    if set(raw.review_id.unique()) != set(REVIEW_IDS):
        raise ValueError('Input must contain exactly the eight expected DTA review IDs')
    filtered = raw.loc[raw.abstract_available].copy()
    if filtered.empty:
        raise ValueError('Abstract-available filter returned no rows')
    filtered.to_csv(output/'scores_nonmissing_abstract.csv', index=False)

    metrics, ranked_parts = [], []
    for rid in REVIEW_IDS:
        m, ranked = evaluate_review(filtered, rid)
        metrics.append(m)
        ranked_parts.append(ranked)
    results = pd.DataFrame(metrics)
    ranked = pd.concat(ranked_parts, ignore_index=True)
    ranked.to_csv(output/'ranked_scores_nonmissing_abstract.csv', index=False)
    results.to_csv(output/'review_metrics.csv', index=False)
    pd.DataFrame([
        {'system':'Jev, filtered non-missing abstracts','setting':'saved zero-shot single-model scores; abstract-available subset',
         'mean_dta_wss95':float(results['WSS@95'].mean()),'mean_dta_wss100':float(results['WSS@100'].mean()),
         'source':'This repository; exact row-level scores in data/jev_dta_scores.csv'},
        {'system':'Akinseloyin et al. (2024)','setting':'Claude 3 criteria QA plus Gemini text-embedding-004 reranking',
         'mean_dta_wss95':.653,'mean_dta_wss100':.573,
         'source':'https://academic.oup.com/jamia/article/31/9/1939/7718667'},
        {'system':'Akinseloyin et al. (2026), Soft-Vote','setting':'zero-shot multi-LLM',
         'mean_dta_wss95':.680,'mean_dta_wss100':.667,
         'source':'https://academic.oup.com/biomethods/article/11/1/bpag006/8460762'},
    ]).to_csv(output/'published_comparison.csv', index=False)

    cutoffs = results.set_index('review_id')['rank_95_recall'].to_dict()
    low = []
    for rid, group in ranked.groupby('review_id', sort=False):
        relevant = group.label_included.astype(int).eq(1)
        for row in group.loc[relevant & ((group['rank'] > cutoffs[rid]) | (group.jev_probability < FIXED_THRESHOLD))].itertuples(index=False):
            low.append({'review_id':rid,'pmid':row.pmid,'label_included':row.label_included,
                'jev_probability':row.jev_probability,'rank':row.rank,
                'percentile_rank_from_top':row.percentile_rank_from_top,
                'rank95_cutoff':cutoffs[rid],
                'flag_reason':'rank beyond the 95% recall cutoff' if row.rank > cutoffs[rid] else 'probability below fixed 0.50 threshold'})
    pd.DataFrame(low).to_csv(output/'low_scoring_positives.csv', index=False)

    aggregate = {col:{'mean':float(results[col].mean()),
                      'sample_sd':float(results[col].std(ddof=1)),
                      'median':float(results[col].median()),
                      'min':float(results[col].min()),
                      'max':float(results[col].max())}
                 for col in ['WSS@95','WSS@100','MAP','Recall@5%','Recall@10%','Recall@20%','Recall@50%']}
    input_hash = digest(source)
    metadata = {
        'analysis':'CLEF-TAR 2019 DTA evaluation restricted to available abstracts',
        'input_file':display_source, 'input_sha256':input_hash,
        'input_rows':int(len(raw)), 'excluded_missing_abstract_rows':int((~raw.abstract_available).sum()),
        'included_rows':int(len(filtered)), 'included_positives':int(filtered.label_included.sum()),
        'review_ids':REVIEW_IDS, 'jev_calls_made':0,
        'abstract_filter':'abstract_available == true; derived from non-null, non-empty trimmed PubMed abstract in scoring metadata',
        'ranking':'descending jev_probability; ties by ascending numeric PMID and then PMID text',
        'WSS@95':'1 - k95/N - 0.05; k95 is first rank reaching ceil(0.95 * positive_count)',
        'WSS@100':'1 - rank_of_last_relevant/N',
        'aggregate':'unweighted arithmetic mean across eight review-level metrics',
        'fixed_probability_threshold':FIXED_THRESHOLD,
        'aggregate_metrics':aggregate,
        'python_version':__import__('sys').version.split()[0],
        'pandas_version':pd.__version__, 'matplotlib_version':matplotlib.__version__,
    }
    (output/'evaluation_metadata.json').write_text(json.dumps(metadata, indent=2)+'\n', encoding='utf-8')

    fig, ax = plt.subplots(figsize=(10,5.5))
    labels = list(results.review_id) + ['Mean']
    values = list(results['WSS@95']) + [results['WSS@95'].mean()]
    ax.bar(labels, values, color=['#4472C4']*len(results)+['#E07A2D'])
    ax.axhline(results['WSS@95'].mean(), color='#E07A2D', linestyle='--', linewidth=1)
    ax.set(ylabel='WSS@95', xlabel='CLEF-TAR 2019 DTA review', title='Jev WSS@95 by review (non-missing abstracts)')
    ax.grid(axis='y', alpha=.25); fig.tight_layout()
    fig.savefig(output/'wss95_by_review.png', dpi=180); plt.close(fig)

    fig, axes = plt.subplots(2,4,figsize=(15,8),sharey=True)
    for ax, rid in zip(axes.flat, REVIEW_IDS):
        d=ranked.loc[ranked.review_id.eq(rid)]
        ax.plot(d['rank']/len(d)*100, d.label_included.astype(int).cumsum()/d.label_included.astype(int).sum()*100, color='#4472C4')
        ax.axhline(95,color='#E07A2D',linestyle='--',linewidth=1)
        ax.set_title(rid); ax.set_xlabel('Records screened (%)'); ax.grid(alpha=.2)
    axes[0,0].set_ylabel('Relevant studies found (%)'); axes[1,0].set_ylabel('Relevant studies found (%)')
    fig.suptitle('Cumulative recall (non-missing abstracts)'); fig.tight_layout()
    fig.savefig(output/'recall_curves.png', dpi=180); plt.close(fig)

    fig, ax = plt.subplots(figsize=(9,5.5))
    for rid in REVIEW_IDS:
        d=ranked.loc[ranked.review_id.eq(rid)]
        ax.hist(d.jev_probability, bins=[i/20 for i in range(21)], histtype='step', linewidth=1.5, label=rid)
    ax.set(xlabel='Jev retain probability', ylabel='Records', title='Score distributions (non-missing abstracts)')
    ax.grid(alpha=.2); ax.legend(fontsize=8); fig.tight_layout()
    fig.savefig(output/'probability_distribution.png', dpi=180); plt.close(fig)

    rows='\n'.join(f"| {r.review_id} | {int(r.total_records):,} | {int(r.number_relevant)} | {r['WSS@95']:.6f} | {r['WSS@100']:.6f} |" for _,r in results.iterrows())
    report=f'''# Filtered Jev evaluation: CLEF-TAR 2019 DTA reviews

Recomputed offline from `{display_source}`. **No Jev calls were made.** The input SHA-256 is `{input_hash}`.

The source file contains {len(raw):,} review-record rows and 440 positive labels. Excluding rows marked as having no non-empty abstract removes {int((~raw.abstract_available).sum()):,} rows and 17 positives. The filtered total is {len(filtered):,} rows ({len(filtered)-26830:+,} versus 26,830), with {int(filtered.label_included.sum())} positives.

Records are ranked within review by descending Jev probability. Ties use ascending numeric PMID, then PMID text. `WSS@95 = 1 - k95/N - 0.05`, where k95 is the first rank reaching at least 95% of positives. `WSS@100 = 1 - rank of the last positive/N`. The aggregate is the unweighted arithmetic mean over eight reviews.

| Review | N | Positives | WSS@95 | WSS@100 |
|---|---:|---:|---:|---:|
{rows}
| **Mean** | **{len(filtered):,}** | **{int(filtered.label_included.sum())}** | **{results['WSS@95'].mean():.6f}** | **{results['WSS@100'].mean():.6f}** |

`review_metrics.csv` includes WSS@95, WSS@100, MAP, recall at 5/10/20/50%, fixed-0.50 threshold metrics, and each review's relevant ranks. `ranked_scores_nonmissing_abstract.csv` preserves the ranked rows; `low_scoring_positives.csv` identifies positives after the WSS@95 cutoff or below the fixed 0.50 threshold. All files omit article text.

`published_comparison.csv` carries forward reported results for context. It is descriptive only: those systems use different criteria representations, models, and ranking procedures, and were not compared head-to-head on this filtered set.
'''
    (output/'README.md').write_text(report, encoding='utf-8')
    print(json.dumps({'output_dir':str(output),'rows':len(filtered),'positives':int(filtered.label_included.sum()),
        'mean_wss95':float(results['WSS@95'].mean()),'mean_wss100':float(results['WSS@100'].mean()),
        'input_sha256':input_hash},indent=2))

if __name__ == '__main__':
    main()
