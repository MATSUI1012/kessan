"""Earnings research snapshot. Only sourced facts; absent fields remain absent.

Inputs: data/earnings.json, prices.json, market-caps.json
Output: data/research.json. No brokerage recommendation is generated.
Dependencies: requests, yfinance, pandas (included with yfinance).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import quote

JST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
MAX_CAP = 1000 * 100_000_000
MIN_CAP = 80 * 100_000_000
MIN_CAP = 80 * 100_000_000
MIN_CAP = 80 * 100_000_000
MIN_CAP = 80 * 100_000_000
MIN_CAP = 80 * 100_000_000
MIN_CAP = 80 * 100_000_000
MIN_CAP = 80 * 100_000_000
MIN_CAP = 80 * 100_000_000
MIN_CAP = 80 * 100_000_000
MIN_CAP = 80 * 100_000_000
MIN_CAP = 80 * 100_000_000
MIN_CAP = 80 * 100_000_000


def utc_now() -> datetime:
    return datetime.now(JST)


def as_num(x):
    try:
        if x is None or isinstance(x, bool):
            return None
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError, OverflowError):
        return None


def percentage(new, old):
    x, y = as_num(new), as_num(old)
    return round(100 * (x / y - 1), 2) if x is not None and y not in (None, 0) else None


def load_array(file: Path):
    raw = json.loads(file.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"Expected list in {file}")
    return raw


def prepare(earnings, prices, caps, now=None, max_count=20, duration=14):
    now = now or utc_now()
    day = now.date()
    caps_map = {str(x.get("code")):as_num(x.get("market_cap_yen")) for x in caps if isinstance(x,dict)}
    bycode = {}
    for p in prices:
        if not isinstance(p, dict):
            continue
        code = str(p.get("code", ""))
        if as_num(p.get("close")) is None or as_num(p.get("volume")) is None:
            continue
        bycode.setdefault(code, []).append(p)
    for rows in bycode.values():
        rows.sort(key=lambda x: str(x.get("date", "")))

    targets=[]
    for e in earnings:
        if not isinstance(e, dict):
            continue
        code = str(e.get("code", ""))
        try:
            event=datetime.strptime(str(e.get("earnings_date")), "%Y-%m-%d").date()
        except (TypeError,ValueError):
            continue
        if not 0 <= (event-day).days <= duration:
            continue
        cap=caps_map.get(code)
        if cap is None or cap < MIN_CAP or cap >= MAX_CAP:
            continue
        series=bycode.get(code,[])
        if not series:
            continue
        last=series[-1]
        try:
            age=(day-datetime.strptime(str(last['date'])[:10],"%Y-%m-%d").date()).days
        except ValueError:
            continue
        if age>7 or age < -1:
            continue
        c=as_num(last.get('close'))
        vol=as_num(last.get('volume'))
        t=(c or 0)*(vol or 0)/1e8
        # No minimum turnover: keep liquidity metrics for information only.
        tail=series[-20:]
        totals=[float(x['close'])*float(x['volume'])/1e8 for x in tail if as_num(x.get('close')) is not None and as_num(x.get('volume')) is not None]
        avgturn=round(sum(totals)/len(totals),2) if totals else None
        vfirst=[as_num(x.get('volume')) for x in series[-25:-5]]
        vlast=[as_num(x.get('volume')) for x in series[-5:]]
        base=[v for v in vfirst if v is not None]
        latest=[v for v in vlast if v is not None]
        vr=round((sum(latest)/len(latest))/(sum(base)/len(base)),2) if base and latest and sum(base)>0 else None
        x5=percentage(c,series[-6]['close']) if len(series)>=6 else None
        x20=percentage(c,series[-21]['close']) if len(series)>=21 else None
        target={
            'code':code,'name':e.get('name',''), 'earnings_date':event.isoformat(),
            'earnings_source':e.get('source_url'), 'market_cap_yen':int(cap),
            'price_date':last.get('date'), 'close':round(c,2),
            'turnover_oku':round(t,2),'avg_turnover_20_oku':avgturn,
            'volume_ratio_5_20':vr,'return_5d':x5,'return_20d':x20,
            '_prices':series,
        }
        targets.append(target)
    # Prioritize recent upcoming events, then liquidity; neither is a buy signal.
    targets.sort(key=lambda x:(x['earnings_date'],-(x['avg_turnover_20_oku'] or 0),x['code']))
    return targets[:max_count]


def financial_summary(statement, period_type="quarterly"):
    """Compare comparable quarters; no annual earnings data are relabeled as quarterly."""
    if statement is None or getattr(statement,'empty',True):
        return None
    cols=sorted(statement.columns,reverse=True)
    lag=4 if period_type=='quarterly' else 1
    if not cols:
        return None
    out={'latest_period':str(cols[0].date()) if hasattr(cols[0],'date') else str(cols[0])[:10], 'period_type':period_type}
    for key,candidates in [
        ('revenue',['Total Revenue','Operating Revenue']),
        ('operating_income',['Operating Income','Operating Income As Reported']),
        ('net_income',['Net Income','Net Income Common Stockholders'])]:
        row=next((n for n in candidates if n in statement.index),None)
        if row is None:
            continue
        latest=as_num(statement.loc[row,cols[0]])
        year_ago=as_num(statement.loc[row,cols[lag]]) if len(cols)>lag else None
        if latest is not None:
            out[key+'_yen']=int(latest)
            out[key+'_yoy_pct']=percentage(latest,year_ago) if year_ago is not None and year_ago>0 else None
    return out if any(k.endswith("_yen") for k in out) else None


def analyst_forecasts(ticker):
    """Returns analyst consensus, never company guidance."""
    result={}
    for name,method,col in [
        ('eps_mean','get_earnings_estimate','avg'),
        ('revenue_mean_yen','get_revenue_estimate','avg')]:
        try:
            df=getattr(ticker,method)()
            if df is None or getattr(df,'empty',True):
                continue
            idx=next((k for k in ['0q','+1q','currentQuarter'] if k in df.index),None)
            if idx is None or col not in df.columns:
                continue
            n=as_num(df.loc[idx,col])
            # Yahoo can return a zero estimate when no analysts cover the stock.
            # Require a positive analyst count instead of treating such placeholders as consensus.
            count_col=next((c for c in ['numberOfAnalysts','numberOfAnalystsAvg'] if c in df.columns),None)
            coverage=as_num(df.loc[idx,count_col]) if count_col else None
            if n is not None and coverage is not None and coverage >= 1 and (name=='eps_mean' or n>0):
                result[name]=round(n,4) if name=='eps_mean' else int(n)
                result['analyst_count']=int(coverage)
                result['period']=str(idx)
        except Exception:
            continue
    return result or None


def event_reactions(ticker,series,now=None):
    """Approximate pre/after earnings-day close returns; not necessarily announcement-hour adjusted."""
    try:
        df=ticker.get_earnings_dates(limit=12)
    except Exception:
        return []
    if df is None or getattr(df,'empty',True):
        return []
    today=(now or utc_now()).date()
    bydate={str(row.get('date',''))[:10]:as_num(row.get('close')) for row in series}
    days=sorted(d for d,v in bydate.items() if v is not None and v>0)
    events=[]
    for idx in df.index:
        try:
            date=idx.date()
        except Exception:
            continue
        if date>=today-timedelta(days=5) or date<today-timedelta(days=385):
            continue
        # Find closing price on most recent trading day before event and next sessions after.
        prev=[d for d in days if d<date.isoformat()]
        aft=[d for d in days if d>date.isoformat()]
        if not prev or len(aft)<5:
            continue
        base=bydate[prev[-1]]
        row=df.loc[idx]
        if hasattr(row,'iloc') and getattr(row,'ndim',1)>1: row=row.iloc[0]
        eps_est=as_num(row.get('EPS Estimate')) if hasattr(row,'get') else None
        eps_act=as_num(row.get('Reported EPS')) if hasattr(row,'get') else None
        surprise=percentage(eps_act,eps_est) if eps_est and eps_est>0 and eps_act is not None else None
        events.append({'event_date':date.isoformat(),'after_1d_pct':percentage(bydate[aft[0]],base),
                       'after_3d_pct':percentage(bydate[aft[2]],base),'after_5d_pct':percentage(bydate[aft[4]],base),
                       'eps_estimate':eps_est,'eps_actual':eps_act,'eps_surprise_pct':surprise,
                       'method':'前営業日終値→発表日後の各営業日終値（時刻未調整）'})
        if len(events)>=4:
            break
    return events


def news_headlines(name,code,now=None,requests_module=None):
    """Retrieve links/headlines, not classify their accuracy or sentiment."""
    if not name:
        return []
    import requests
    rm=requests_module or requests
    q=quote(f'"{name}" 決算 when:14d')
    url='https://news.google.com/rss/search?q='+q+'&hl=ja&gl=JP&ceid=JP:ja'
    try:
        resp=rm.get(url,headers={'User-Agent':'Mozilla/5.0'},timeout=12)
        resp.raise_for_status()
        root=ET.fromstring(resp.content)
        out=[]
        for item in root.findall('.//channel/item'):
            title=item.findtext('title','')
            link=item.findtext('link','')
            pub=item.findtext('pubDate','')
            if not link.startswith('https://') or not title:
                continue
            # Preserve the original source instead of pretending all news is an IR filing.
            src=item.find('source')
            publisher=src.text if src is not None else None
            try:
                stamp=parsedate_to_datetime(pub).astimezone(JST).isoformat(timespec='minutes')
            except Exception:
                stamp=None
            out.append({'title':title[:250], 'url':link, 'source':publisher, 'published_at':stamp})
            if len(out)>=5:
                break
        return out
    except Exception:
        return []


def yahoo_research(code,series,now=None,finance_module=None):
    if finance_module is None:
        import yfinance as finance_module
    ticker=finance_module.Ticker(f'{code}.T')
    result={'financials':None,'analyst_consensus':None,'prior_reactions':[], 'sources':{'fundamentals':f'https://finance.yahoo.com/quote/{code}.T/financials/',
           'estimates':f'https://finance.yahoo.com/quote/{code}.T/analysis/'}}
    try:
        stmt=ticker.get_income_stmt(freq='quarterly')
        result['financials']=financial_summary(stmt)
    except Exception:
        pass
    if not result['financials'] or result['financials'].get('revenue_yoy_pct') is None:
        try:
            yearly=ticker.get_income_stmt(freq='yearly')
            annual=financial_summary(yearly, period_type='yearly')
            if annual and annual.get('revenue_yoy_pct') is not None:
                result['financials']=annual
        except Exception:
            pass
    # EARNINGS_EVIDENCE_REPAIR_V1
    # Japanese equities are often missing quarterly statements and earnings
    # dates on Yahoo Finance. Use summary data only with explicit TTM labels.
    if not result['financials']:
        try:
            information = ticker.get_info()
            if isinstance(information, dict):
                revenue = as_num(information.get('totalRevenue'))
                if revenue is not None and revenue > 0:
                    result['financials'] = {
                        'revenue_yen': int(revenue),
                        'period_type': 'ttm',
                        'latest_period': None,
                        'data_source': 'Yahoo Finance TTM summary, not company IR',
                        'revenue_yoy_pct': None,
                        'operating_income_yoy_pct': None,
                    }
        except Exception as exc:
            result['fundamental_error_type'] = type(exc).__name__
    result['analyst_consensus']=analyst_forecasts(ticker)
    result['prior_reactions']=event_reactions(ticker,series,now=now)
    result['missing_data']=[]
    if not result['financials']:
        result['missing_data'].append('Financial results unavailable: company IR not verified')
    elif result['financials'].get('period_type') == 'ttm':
        result['missing_data'].append('Only TTM revenue available; quarterly year-on-year change unknown')
    if not result['prior_reactions']:
        result['missing_data'].append('Historical earnings dates or surrounding daily price data unavailable')
    return result


def score_record(r):
    """Transparent *research priority* points, never a probability of beating earnings."""
    components=[]
    v=as_num(r.get('volume_ratio_5_20'))
    if v is not None and v>=1.5:
        components.append({'label':'直近出来高が増加（5日平均/前20日平均）','points':2})
    ret=as_num(r.get('return_20d'))
    if ret is not None and 0 < ret <= 20:
        components.append({'label':'20営業日で緩やかな上昇','points':1})
    rev=(r.get('financials') or {}).get('revenue_yoy_pct')
    if rev is not None and rev>5:
        components.append({'label':('直近通期' if (r.get('financials') or {}).get('period_type')=='yearly' else '直近四半期')+'売上高が前年同期比5%超増','points':2})
    op=(r.get('financials') or {}).get('operating_income_yoy_pct')
    if op is not None and op>10:
        components.append({'label':('直近通期' if (r.get('financials') or {}).get('period_type')=='yearly' else '直近四半期')+'営業利益が前年同期比10%超増','points':2})
    consensus = r.get('analyst_consensus') or {}
    if (as_num(consensus.get('analyst_count')) or 0)>=1 and ('eps_mean' in consensus or (as_num(consensus.get('revenue_mean_yen')) or 0)>0):
        components.append({'label':'担当アナリスト数を確認できる市場予想あり','points':1})
    reactions=r.get('prior_reactions') or []
    beats=[x['eps_surprise_pct'] for x in reactions if x.get('eps_surprise_pct') is not None]
    if len(beats)>=2 and sum(x>0 for x in beats)/len(beats)>=0.6:
        components.append({'label':'過去決算のEPS予想超過が確認できる','points':1})
    elif reactions:
        components.append({'label':'過去決算日付近の株価反応データあり','points':1})
    return {'research_priority_score':sum(x['points'] for x in components),
            'signals':components,'evidence_count':sum(bool(r.get(x)) for x in ['financials','prior_reactions','news']) + int(bool((r.get('analyst_consensus') or {}).get('analyst_count')))}


def build_snapshot(earnings,prices,caps,now=None,limit=20,finance_module=None,request_module=None,sleep=0.25):
    now=now or utc_now()
    prepared=prepare(earnings,prices,caps,now=now,max_count=limit)
    records=[]
    for i,record in enumerate(prepared,1):
        print(f'{i}/{len(prepared)} researching {record["code"]}',flush=True)
        series=record.pop('_prices')
        try:
            record.update(yahoo_research(record['code'],series,now=now,finance_module=finance_module))
        except Exception as exc:
            record.update({'financials':None,'analyst_consensus':None,'prior_reactions':[], 'sources':{},
                           'fetch_error_type':type(exc).__name__})
        record['news']=news_headlines(record['name'],record['code'],now,requests_module=request_module)
        record.update(score_record(record))
        records.append(record)
        if sleep:
            time.sleep(sleep)
    records.sort(key=lambda x:(-x['research_priority_score'],-x['evidence_count'],x['earnings_date'],-x['turnover_oku']))
    return {'generated_at':now.isoformat(timespec='seconds'),
            'schema':1,'screening':{'days_ahead':14,'market_cap_min_yen_inclusive':MIN_CAP,'market_cap_max_yen_exclusive':MAX_CAP,'min_latest_turnover_oku':0},
            'records':records,'count':len(records),
            'method':'調査優先度は公開価格・出来高・取得できた四半期業績等のみ。買い推奨や決算予測確率ではありません。'}


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--limit',type=int,default=20)
    ap.add_argument('--data-dir',type=Path,default=DATA)
    args=ap.parse_args()
    earnings=load_array(args.data_dir/'earnings.json')
    prices=load_array(args.data_dir/'prices.json')
    caps=load_array(args.data_dir/'market-caps.json')
    if not earnings or not prices or not caps:
        raise RuntimeError('Source data missing/empty; retaining old snapshot')
    doc=build_snapshot(earnings,prices,caps,limit=max(1,min(40,args.limit)))
    # A successful run with zero candidates is a valid empty snapshot.
    args.data_dir.mkdir(exist_ok=True,parents=True)
    (args.data_dir/'research.json').write_text(json.dumps(doc,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Saved research snapshot:',doc['count'],flush=True)

if __name__=='__main__':
    main()
