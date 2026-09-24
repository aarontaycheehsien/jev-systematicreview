from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd

THRESHOLDS=[i/10 for i in range(1,10)]

def main():
    root=Path(__file__).resolve().parents[1]
    parser=argparse.ArgumentParser(description='Offline evaluation of saved Donners_2021 Jev scores.')
    parser.add_argument('--input',type=Path,default=root/'data'/'jev_donners2021_scores.csv')
    parser.add_argument('--output-dir',type=Path,default=root/'results'/'donners_2021')
    args=parser.parse_args(); source=args.input.resolve(); out=args.output_dir.resolve(); out.mkdir(parents=True,exist_ok=True)
    d=pd.read_csv(source,dtype={'record_id':str})
    needed={'record_id','label_included','jev_probability','abstract_available'}
    if needed-set(d): raise ValueError(f'Missing fields: {sorted(needed-set(d))}')
    if d.jev_probability.isna().any() or d.label_included.isna().any(): raise ValueError('Expected complete saved scores and labels')
    if d.record_id.duplicated().any(): raise ValueError('record_id must be unique')
    y=d.label_included.astype(int); p=d.jev_probability.astype(float)
    rows=[]
    for t in THRESHOLDS:
        keep=p>=t; tp=int((keep&(y==1)).sum()); fn=int(((~keep)&(y==1)).sum()); tn=int(((~keep)&(y==0)).sum()); fp=int((keep&(y==0)).sum())
        rows.append({'threshold':t,'true_positives':tp,'false_negatives':fn,'true_negatives':tn,'false_positives':fp,'recall':tp/(tp+fn),'specificity':tn/(tn+fp),'precision':tp/(tp+fp) if tp+fp else float('nan'),'retained_for_human_screening':int(keep.sum()),'automatically_excluded':int((~keep).sum()),'workload_reduction_pct':float((~keep).sum()/len(d)*100)})
    thresholds=pd.DataFrame(rows); thresholds.to_csv(out/'threshold_results.csv',index=False)
    positives=d.loc[y.eq(1)].copy(); negatives=d.loc[y.eq(0)].copy(); min_pos=float(positives.jev_probability.min()); oracle=p>=min_pos
    positives.sort_values('jev_probability').to_csv(out/'included_studies_ranked.csv',index=False)
    negatives.sort_values('jev_probability',ascending=False).head(10).to_csv(out/'highest_scoring_excluded.csv',index=False)
    oracle_metrics={'threshold':min_pos,'included_retained':int(((y==1)&oracle).sum()),'included_missed':int(((y==1)&(~oracle)).sum()),'records_retained':int(oracle.sum()),'excluded':int((~oracle).sum()),'workload_reduction_pct':float((~oracle).sum()/len(d)*100)}
    at50=thresholds.loc[thresholds.threshold.eq(.5)].iloc[0]
    curve95=float(positives.jev_probability.sort_values().iloc[max(0,int((.05*len(positives))//1))])
    h=hashlib.sha256(source.read_bytes()).hexdigest()
    metadata={'input_file':source.relative_to(root).as_posix() if source.is_relative_to(root) else args.input.as_posix(),'input_sha256':h,'records':len(d),'included':int(y.sum()),'excluded':int((y==0).sum()),'missing_abstracts':int((~d.abstract_available.astype(bool)).sum()),'api_errors':0,'jev_calls_made':0,'model':', '.join(sorted(d.jev_model.dropna().astype(str).unique())) if 'jev_model' in d else 'not recorded','oracle_metrics':oracle_metrics,'fixed_threshold_0.50':at50.to_dict(),'input_output_tokens':[int(d.input_tokens.sum()),int(d.output_tokens.sum())] if {'input_tokens','output_tokens'}<=set(d) else None}
    (out/'evaluation_metadata.json').write_text(json.dumps(metadata,indent=2)+'\n',encoding='utf-8')
    fig,ax=plt.subplots(figsize=(7,5)); ax.plot(thresholds.workload_reduction_pct,thresholds.recall*100,marker='o',label='Fixed thresholds'); ax.scatter([oracle_metrics['workload_reduction_pct']],[100],marker='*',s=160,color='crimson',label='Post-hoc 100% recall'); ax.set(xlabel='Workload reduction (%)',ylabel='Recall of ultimately included studies (%)',xlim=(0,100),ylim=(0,105)); ax.grid(alpha=.25); ax.legend(); fig.tight_layout(); fig.savefig(out/'recall_vs_workload.png',dpi=160); plt.close(fig)
    fig,ax=plt.subplots(figsize=(7,5)); ax.hist(negatives.jev_probability,bins=12,alpha=.65,label=f'Ultimately excluded (n={len(negatives)})'); ax.hist(positives.jev_probability,bins=12,alpha=.75,label=f'Ultimately included (n={len(positives)})'); ax.set(xlabel='Jev probability of retain',ylabel='Records',xlim=(0,1)); ax.grid(axis='y',alpha=.25); ax.legend(); fig.tight_layout(); fig.savefig(out/'probability_distribution.png',dpi=160); plt.close(fig)
    summary=f'''# Donners_2021 saved-score evaluation

This evaluation recomputes threshold metrics from the released score file. **No Jev calls were made.** Input SHA-256: `{h}`.

## Dataset

- Records: {len(d)}
- Ultimately included: {int(y.sum())}
- Ultimately excluded: {int((y==0).sum())}
- Missing abstracts: {int((~d.abstract_available.astype(bool)).sum())}
- Model: {metadata['model']}

## Post-hoc oracle description

At the label-informed 100%-recall threshold of {min_pos:.4f}, all {int(y.sum())} ultimately included studies are retained and {oracle_metrics['excluded']} of {len(d)} records would be excluded, a workload reduction of {oracle_metrics['workload_reduction_pct']:.1f}%. This is a post-hoc description using the same labels, not a prospectively validated threshold.

## Fixed threshold 0.50

- True positives: {int(at50.true_positives)}; false negatives: {int(at50.false_negatives)}
- True negatives: {int(at50.true_negatives)}; false positives: {int(at50.false_positives)}
- Recall: {at50.recall:.1%}; specificity: {at50.specificity:.1%}; precision: {at50.precision:.1%}
- Retained: {int(at50.retained_for_human_screening)}; automatically excluded: {int(at50.automatically_excluded)}
- Workload reduction: {at50.workload_reduction_pct:.1f}%

The benchmark label is final inclusion in one review, not a record of the original title/abstract screening decision. This retrospective single-review experiment does not validate autonomous screening.
'''
    (out/'README.md').write_text(summary,encoding='utf-8')
    print(json.dumps({'records':len(d),'included':int(y.sum()),'wrote':str(out),'sha256':h},indent=2))
if __name__=='__main__': main()
