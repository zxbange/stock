#!/usr/bin/env python3
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
import sys
sys.path.insert(0, str(PROJECT_ROOT / 'src'))
from utils.log_config import get_logger
logger = get_logger("生成ETF列表")
"""生成ETF indicators目录清单到 today/etf_list.json"""
import json, csv, pandas as pd

DATA_DIR = PROJECT_ROOT / 'data/etf'
IND_DIR  = Path('/home/bange/stock/daily_result/today/indicators_etf')
OUT     = Path('/home/bange/stock/daily_result/today/etf_list.json')

etf_list_path = DATA_DIR / 'etf_list.csv'
BLACKLIST_FILE = PROJECT_ROOT / 'etf_blacklist.txt'

def load_blacklist():
    """加载黑名单ETF列表"""
    bl = set()
    if BLACKLIST_FILE.exists():
        with open(BLACKLIST_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                code = line.strip()
                if code:
                    bl.add(code)
    return bl

blacklist = load_blacklist()
if blacklist:
    print(f"黑名单: {len(blacklist)} 只，将被过滤")

def get_latest_amount(ts_code: str) -> float:
    """从各ETF的CSV读取最新交易日的amount（用于排序）"""
    csv_path = DATA_DIR / f'{ts_code}.csv'
    if not csv_path.exists() or csv_path.stat().st_size < 100:
        return 0.0
    try:
        df = pd.read_csv(csv_path, usecols=['date','amount'], parse_dates=['date'])
        if df.empty:
            return 0.0
        latest = df.sort_values('date').iloc[-1]
        return float(latest['amount']) if not pd.isna(latest['amount']) else 0.0
    except Exception:
        return 0.0

# 按benchmark分组
bench_data = {}
with open(etf_list_path) as f:
    for row in csv.DictReader(f):
        ts_code = row['ts_code'].strip()
        name    = row['name'].strip()
        bench   = row.get('benchmark', '') or '未知指数'
        # 跳过黑名单ETF
        if blacklist and ts_code in blacklist:
            continue
        # 只包含有indicators的ETF
        if not (IND_DIR / f'{ts_code}.json').exists():
            continue
        amount = get_latest_amount(ts_code)
        bench_data.setdefault(bench, []).append({
            'ts_code': ts_code,
            'name': name,
            'benchmark': bench,
            'amount': amount
        })

# 按成交额排序
for bench in bench_data:
    bench_data[bench].sort(key=lambda x: -x['amount'])

total = sum(len(v) for v in bench_data.values())
print(f"ETF分组: {len(bench_data)}, 有indicators: {total}")

with open(OUT, 'w', encoding='utf-8') as f:
    json.dump(bench_data, f, ensure_ascii=False)
print(f"已写入: {OUT}")
