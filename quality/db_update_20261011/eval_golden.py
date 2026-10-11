
import json, sys, os, time, re
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')
repo = Path(sys.argv[1]); db = Path(sys.argv[2]); out = Path(sys.argv[3])
mapping = json.loads(Path(sys.argv[4]).read_text(encoding='utf-8')) if len(sys.argv) > 4 else None
os.chdir(repo); sys.path.insert(0, str(repo))
from welfare_search import retrieve_context
gold = json.loads((repo/'quality'/'golden_qa_v1.4.0.json').read_text(encoding='utf-8'))['items']
rows = []
t0 = time.time()
for item in gold:
    ctx = retrieve_context(db, item['question'], limit=7, char_budget=14_000)
    srcs = []
    for b in ctx.blocks:
        md = getattr(b, 'metadata', None) or {}
        s = md.get('source_name') or md.get('source') or ''
        srcs.append(s)
    exp = item['expected_document']
    exp_set = set(mapping.get(item['id'], [])) if mapping is not None else {exp}
    nums = [str(n) for n in item['expected_numbers']]
    text = str(ctx)
    compact = re.sub(r'\s+', '', text)
    rows.append({'id': item['id'], 'category': item['category'], 'expected': sorted(exp_set),
                 'top1': srcs[0] if srcs else '', 'sources': srcs,
                 'doc_hit_top1': bool(srcs) and srcs[0] in exp_set,
                 'doc_hit_any': any(s in exp_set for s in srcs),
                 'section_term': item['expected_section'] in text or re.sub(r'\s+','',item['expected_section']) in compact,
                 'numbers_total': len(nums), 'numbers_found': sum(re.sub(r'\s+','',n) in compact for n in nums),
                 'must_include_total': len(item['must_include']), 'must_include_found': sum(re.sub(r'\s+','',m) in compact for m in item['must_include']),
                 'chars': len(text)})
elapsed = time.time() - t0
def pct(k): return round(100*sum(r[k] for r in rows)/len(rows),1)
summary = {'db': str(db), 'items': len(rows), 'doc_hit_top1_pct': pct('doc_hit_top1'), 'doc_hit_any_pct': pct('doc_hit_any'),
           'section_term_pct': pct('section_term'),
           'numbers': [sum(r['numbers_found'] for r in rows), sum(r['numbers_total'] for r in rows)],
           'must_include': [sum(r['must_include_found'] for r in rows), sum(r['must_include_total'] for r in rows)],
           'avg_seconds': round(elapsed/len(rows),3)}
out.write_text(json.dumps({'summary': summary, 'rows': rows}, ensure_ascii=False, indent=1), encoding='utf-8')
print(json.dumps(summary, ensure_ascii=False))
if rows and not any(rows[i]['sources'] for i in range(len(rows))): print('WARNING no sources parsed', dir(ctx.blocks[0]) if ctx.blocks else None)

