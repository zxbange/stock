#!/usr/bin/env python3
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
import sys
sys.path.insert(0, str(PROJECT_ROOT / 'src'))
from utils.log_config import get_logger
logger = get_logger("生成ETF列表")
"""生成ETF indicators目录清单到 today/etf_list.json"""
import json, csv

DATA_DIR = PROJECT_ROOT / 'data/etf'
IND_DIR  = Path('/home/bange/stock/daily_result/today/indicators_etf')
OUT     = Path('/home/bange/stock/daily_result/today/etf_list.json')

etf_list_path = DATA_DIR / 'etf_list.csv'

# 按benchmark分组
bench_data = {}
with open(etf_list_path) as f:
    for row in csv.DictReader(f):
        ts_code = row['ts_code'].strip()
        name    = row['name'].strip()
        bench   = row.get('benchmark', '') or '未知指数'
        amount  = float(row.get('amount') or 0)
        # 只包含有indicators的ETF
        if not (IND_DIR / f'{ts_code}.json').exists():
            continue
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
