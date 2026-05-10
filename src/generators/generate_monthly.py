#!/usr/bin/env python3
"""
generate_monthly.py - 将日线数据聚合为月K线数据
"""
import json, os, sys
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from itertools import chain

DATA_DIR = "/home/bange/stock/data_kline"

def calc_ema(values, period):
    """计算EMA"""
    if len(values) < period:
        return [None] * len(values)
    k = 2.0 / (period + 1)
    ema = []
    # Find first non-None
    first = None
    for i, v in enumerate(values):
        if v is not None:
            first = v
            ema = [None] * i
            break
    if first is None:
        return [None] * len(values)
    ema.append(first)
    for v in values[1:]:
        if v is None:
            ema.append(None)
        else:
            ema.append(v if ema[-1] is None else ema[-1] * (1 - k) + v * k)
    return ema

def calc_sma(values, period):
    """计算SMA"""
    if len(values) < period:
        return [None] * len(values)
    result = [None] * (period - 1)
    for i in range(period - 1, len(values)):
        s = sum(values[i - period + 1:i + 1])
        result.append(s / period)
    return result

def process_one(code):
    """处理单个股票，返回(code, error)"""
    csv_path = os.path.join(DATA_DIR, f"{code}.csv")
    out_path = os.path.join(DATA_DIR, f"{code}_monthly.json")

    # Skip if already exists
    if os.path.exists(out_path):
        return code, None

    try:
        rows = []
        with open(csv_path, "r") as f:
            header = f.readline()
            for line in f:
                parts = line.strip().split(",")
                if len(parts) < 10:
                    continue
                # date is parts[1], format: 2024-01-02
                date = parts[1]
                rows.append({
                    "date": date,       # YYYY-MM-DD
                    "o": float(parts[2]),
                    "h": float(parts[3]),
                    "l": float(parts[4]),
                    "c": float(parts[5]),
                    "v": float(parts[9])
                })
    except Exception as e:
        return code, str(e)

    if not rows:
        return code, "no data"

    # Sort by date
    rows.sort(key=lambda x: x["date"])

    # Group by month: key = "YYYY-MM"
    months = defaultdict(list)
    for r in rows:
        ym = r["date"][:7]  # "YYYY-MM"
        months[ym].append(r)

    # Sort month keys
    sorted_months = sorted(months.keys())

    monthly_rows = []
    for ym in sorted_months:
        mr = months[ym]
        month_close = float(mr[-1]["c"])
        # pct: compare first row's close to previous month close
        monthly_rows.append({
            "time": ym + "-01",
            "o": mr[0]["o"],
            "h": max(r["h"] for r in mr),
            "l": min(r["l"] for r in mr),
            "c": month_close,
            "v": sum(r["v"] for r in mr),
            "pct": 0.0  # placeholder, will compute below
        })

    N = len(monthly_rows)
    if N == 0:
        return code, "no monthly rows"

    # Compute pct: compare each month's close to previous month's close
    closes = [r["c"] for r in monthly_rows]
    for i in range(1, N):
        if closes[i - 1] and closes[i - 1] != 0:
            monthly_rows[i]["pct"] = (closes[i] - closes[i - 1]) / closes[i - 1] * 100
        else:
            monthly_rows[i]["pct"] = 0.0

    times = [r["time"] for r in monthly_rows]

    # --- MA ---
    ma5 = calc_sma(closes, 5)
    ma10 = calc_sma(closes, 10)
    ma20 = calc_sma(closes, 20)
    ma30 = calc_sma(closes, 30)
    ma60 = calc_sma(closes, 60)
    ma120 = calc_sma(closes, 120)
    ma240 = calc_sma(closes, 240)

    # --- MACD: DIF = EMA(close,12) - EMA(close,26), DEA = EMA(DIF,9), MACD = (DIF-DEA)*2 ---
    dif = [None] * N
    dea = [None] * N
    macd = [None] * N

    c_ema12 = calc_ema(closes, 12)
    c_ema26 = calc_ema(closes, 26)
    for i in range(N):
        if c_ema12[i] is not None and c_ema26[i] is not None:
            dif[i] = c_ema12[i] - c_ema26[i]
        else:
            dif[i] = None

    dea = calc_ema(dif, 9)
    for i in range(N):
        if dif[i] is not None and dea[i] is not None:
            macd[i] = (dif[i] - dea[i]) * 2
        else:
            macd[i] = None

    # --- KDJ: 9-period ---
    RSV = [None] * N
    K = [None] * N
    D = [None] * N
    J = [None] * N

    period_kdj = 9
    for i in range(N):
        window = monthly_rows[max(0, i - period_kdj + 1):i + 1]
        low_min = min(r["l"] for r in window)
        high_max = max(r["h"] for r in window)
        close_val = monthly_rows[i]["c"]
        if high_max != low_min:
            RSV[i] = (close_val - low_min) / (high_max - low_min) * 100
        else:
            RSV[i] = 50

    K_val = 50.0
    D_val = 50.0
    for i in range(N):
        if RSV[i] is not None:
            K_val = K_val * 2 / 3 + RSV[i] / 3
            D_val = D_val * 2 / 3 + K_val / 3
            J_val = 3 * K_val - 2 * D_val
        else:
            K_val = None
            D_val = None
            J_val = None
        K[i] = K_val
        D[i] = D_val
        J[i] = J_val

    indicators = {
        "ma5": ma5, "ma10": ma10, "ma20": ma20, "ma30": ma30,
        "ma60": ma60, "ma120": ma120, "ma240": ma240,
        "dif": dif, "dea": dea, "macd": macd,
        "K": K, "D": D, "J": J
    }

    result = {
        "period": "M",
        "times": times,
        "rows": monthly_rows,
        "indicators": indicators
    }

    with open(out_path, "w") as f:
        json.dump(result, f, ensure_ascii=False)

    return code, None

def get_all_codes():
    """获取所有有日线csv但没有月线json的股票"""
    files = os.listdir(DATA_DIR)
    codes = set()
    for f in files:
        if f.endswith(".csv") and not f.endswith("_weekly.csv") and not f.endswith("_monthly.csv"):
            code = f[:-4]  # strip .csv
            codes.add(code)
    return list(codes)

def main():
    codes = get_all_codes()
    print(f"Found {len(codes)} stocks to process for monthly data")

    done = 0
    errors = []
    with ProcessPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(process_one, code): code for code in codes}
        for future in as_completed(futures):
            code, err = future.result()
            if err:
                errors.append((code, err))
                print(f"ERROR {code}: {err}")
            else:
                done += 1
                if done % 200 == 0:
                    print(f"Processed {done}/{len(codes)}")

    print(f"Done! {done} stocks processed, {len(errors)} errors")
    if errors:
        for code, err in errors[:10]:
            print(f"  {code}: {err}")

if __name__ == "__main__":
    main()