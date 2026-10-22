#!/usr/bin/env python3
"""Review frozen human earnings forecasts against next-session observations."""
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

DATA = Path(__file__).resolve().parent / 'data'

def load(name, default):
    path = DATA / name
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default

def parsed(s):
    try:
        return datetime.fromisoformat(str(s).replace('Z', '+00:00'))
    except (TypeError, ValueError):
        return None

def review():
    decisions = load('human-judgments.json', {'decisions': []}).get('decisions', [])
    outcomes = load('earnings-nextday-reactions.json', {'records': []}).get('records', [])
    by_key = defaultdict(list)
    for r in outcomes:
        if isinstance(r, dict):
            by_key[(str(r.get('code', '')), str(r.get('scheduled_date', ''))[:10])].append(r)
    results, invalid, pending = [], [], []
    for row in decisions:
        if not isinstance(row, dict):
            invalid.append({'reason': 'invalid record'})
            continue
        code = str(row.get('code', ''))
        event = str(row.get('earnings_date', ''))[:10]
        stamped = parsed(row.get('recorded_at'))
        start = parsed(event + 'T00:00:00+09:00')
        prediction = row.get('expectation')
        if not (code and stamped and stamped.tzinfo and start and stamped < start
                and prediction in ('up', 'down', 'neutral') and str(row.get('reason', '')).strip()):
            invalid.append({'code': code, 'earnings_date': event, 'reason': 'missing or non-frozen evidence'})
            continue
        eligible = [r for r in by_key[(code, event)]
                    if type(r.get('next_close_pct')) in (float, int)
                    and str(r.get('next_session_date', ''))[:10] > event]
        if not eligible:
            pending.append({'code': code, 'earnings_date': event})
            continue
        o = sorted(eligible, key=lambda r: (not bool(r.get('ohlc_complete')),
                                            str(r.get('next_session_date', ''))))[0]
        value = o['next_close_pct']
        actual = 'up' if value > 0 else 'down' if value < 0 else 'neutral'
        results.append({'code': code, 'earnings_date': event, 'recorded_at': row['recorded_at'],
                        'prediction': prediction, 'actual': actual, 'correct': prediction == actual,
                        'next_close_pct': value, 'reason': row['reason'],
                        'confidence': row.get('confidence'), 'tags': row.get('tags', [])})
    n = len(results)
    return {'schema': 1, 'total': len(decisions), 'reviewed': n, 'correct': sum(r['correct'] for r in results),
            'accuracy': round(sum(r['correct'] for r in results)/n, 4) if n else None,
            'by_prediction': {p: {'n': sum(r['prediction']==p for r in results),
                                  'correct': sum(r['prediction']==p and r['correct'] for r in results)}
                              for p in ('up','down','neutral')},
            'invalid': invalid, 'awaiting_outcome': pending, 'comparisons': results,
            'warnings': ['Next-session price change is not necessarily caused by earnings.',
                         'JPX scheduled dates are not verified disclosure timestamps.',
                         'Missing evidence is not a zero score. Do not optimize on tiny samples.']}

if __name__ == '__main__':
    DATA.mkdir(exist_ok=True)
    result = review()
    (DATA/'human-judgment-review.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({k:result[k] for k in ('total','reviewed','correct','accuracy')}))
