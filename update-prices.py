"""GitHub Actions: 株価と時価総額を更新する。推定値は作らない。"""
import json
import time
from datetime import datetime, date, timedelta, timezone
from pathlib import Path
import requests
import yfinance as yf

BASE = Path('data')
EARNINGS = BASE / 'earnings.json'
OUTPUT = BASE / 'prices.json'
CAP_OUTPUT = BASE / 'market-caps.json'
JST = timezone(timedelta(hours=9))


def fetch_prices(code, session):
    endpoint = f'https://query1.finance.yahoo.com/v8/finance/chart/{code}.T'
    params = {'period1': int(time.time()-400*86400), 'period2': int(time.time()), 'interval':'1d'}
    response = session.get(endpoint, params=params, timeout=25)
    response.raise_for_status()
    data = response.json()['chart']['result']
    if not data: return []
    item = data[0]
    quote = item['indicators']['quote'][0]
    result = []
    for i, ts in enumerate(item.get('timestamp') or []):
        close = quote['close'][i]
        if close is None: continue
        result.append({'code':code, 'date':datetime.fromtimestamp(ts, JST).date().isoformat(),
                       'close':round(float(close),3), 'volume':quote['volume'][i]})
    return result


def fetch_cap(code):
    try:
        cap = yf.Ticker(f'{code}.T').fast_info.market_cap
        cap = int(cap)
        if cap <= 0: raise ValueError('no market cap')
        return cap
    except Exception as err:
        print('Market cap unavailable:', code, repr(err))
        return None


def main():
    earnings = json.loads(EARNINGS.read_text(encoding='utf-8'))
    today = datetime.now(JST).date()
    start = today - timedelta(days=14)
    end = today + timedelta(days=30)
    codes = sorted({str(e.get('code','')).strip() for e in earnings
                    if isinstance(e,dict) and start.isoformat() <= str(e.get('earnings_date','')) <= end.isoformat()
                    and str(e.get('code','')).strip().isdigit()})
    session = requests.Session()
    session.headers['User-Agent'] = 'Mozilla/5.0'
    all_prices, caps = [], []
    for code in codes:
        try:
            all_prices.extend(fetch_prices(code,session))
        except Exception as err:
            print('Prices unavailable:',code,repr(err))
        cap = fetch_cap(code)
        caps.append({'code':code, 'market_cap_yen':cap,
                     'updated_at':datetime.now(JST).isoformat(timespec='seconds') if cap is not None else None})
        time.sleep(0.3)
    BASE.mkdir(exist_ok=True)
    # Do not replace valid published prices with an empty response caused by transient failure.
    if all_prices:
        OUTPUT.write_text(json.dumps(all_prices,ensure_ascii=False),encoding='utf-8')
    else:
        print('No prices fetched; existing prices preserved')
    CAP_OUTPUT.write_text(json.dumps(caps,ensure_ascii=False),encoding='utf-8')
    print('Saved',len(all_prices),'price rows,',sum(x['market_cap_yen'] is not None for x in caps),'market caps')

if __name__ == '__main__':
    main()
