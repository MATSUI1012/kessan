
import json
import time
from datetime import date, timedelta
from pathlib import Path

import requests

BASE = Path("data")
EARNINGS = BASE / "earnings.json"
OUTPUT = BASE / "prices.json"

def fetch_prices(code):
    symbol = f"{code}.T"
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    params = {
        "period1": int(time.time() - 400 * 86400),
        "period2": int(time.time()),
        "interval": "1d",
    }
    response = requests.get(
        url,
        params=params,
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=20,
    )
    response.raise_for_status()
    result = response.json()["chart"]["result"]
    if not result:
        return []
    item = result[0]
    timestamps = item.get("timestamp", [])
    quote = item["indicators"]["quote"][0]
    rows = []
    for i, ts in enumerate(timestamps):
        close = quote["close"][i]
        volume = quote["volume"][i]
        if close is None:
            continue
        rows.append({
            "code": code,
            "date": date.fromtimestamp(ts).isoformat(),
            "close": round(float(close), 3),
            "volume": volume,
        })
    return rows

def main():
    if not EARNINGS.exists():
        raise RuntimeError("earnings.json がありません")

    earnings = json.loads(EARNINGS.read_text(encoding="utf-8"))
    today = date.today()
    start = today - timedelta(days=40)
    codes = sorted({
        str(item.get("code", "")).strip()
        for item in earnings
        if isinstance(item, dict)
        and start.isoformat() <= str(item.get("date", "")) <= today.isoformat()
        and str(item.get("code", "")).strip().isdigit()
    })

    all_rows = []
    for code in codes:
        try:
            rows = fetch_prices(code)
            all_rows.extend(rows)
            print(code, len(rows), "rows")
        except Exception as exc:
            print(code, "SKIPPED:", exc)
        time.sleep(0.5)

    BASE.mkdir(exist_ok=True)
    OUTPUT.write_text(
        json.dumps(all_rows, ensure_ascii=False),
        encoding="utf-8",
    )
    print("Saved", len(all_rows), "price rows")

if __name__ == "__main__":
    main()
