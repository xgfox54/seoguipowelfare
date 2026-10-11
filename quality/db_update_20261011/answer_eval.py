
import json, os, re, sys, threading, time
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')
root = Path(sys.argv[1]); out = Path(sys.argv[2]); ids = sys.argv[3].split(',')
os.environ['MODEL_VARIANT'] = 'E2B'; os.environ['WELFARE_MODEL_VARIANT'] = 'E2B'
os.chdir(root); sys.path.insert(0, str(root))
from welfare_llm import RUNTIME
import welfare_assistant
gold = {i['id']: i for i in json.loads((root / 'quality' / 'golden_qa_v1.4.0.json').read_text(encoding='utf-8'))['items']}
threading.Thread(target=RUNTIME.start, daemon=True).start()
t0 = time.time()
while RUNTIME.state != 'ready':
    if RUNTIME.state == 'error' or time.time() - t0 > 900: raise SystemExit('engine ' + RUNTIME.state)
    time.sleep(2)
print('engine ready', round(time.time() - t0), 's', flush=True)
rows = []
for qid in ids:
    item = gold[qid]; t = time.time()
    answer = welfare_assistant.answer_question(root, item['question'], 'gemma_e2b')
    compact = re.sub(r'\s+', '', answer)
    hits = [n for n in item['expected_numbers'] if re.sub(r'\s+', '', n) in compact]
    rows.append({'id': qid, 'question': item['question'], 'seconds': round(time.time() - t, 1), 'expected_numbers': item['expected_numbers'], 'number_hits': hits, 'answer': answer})
    print(qid, rows[-1]['seconds'], 's', 'hits', hits, '/', item['expected_numbers'], '|', answer[:160].replace('\n', ' '), flush=True)
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding='utf-8')
RUNTIME.stop()
print('numeric', sum(bool(r['number_hits']) for r in rows if r['expected_numbers']), '/', sum(bool(r['expected_numbers']) for r in rows))

