#!/usr/bin/env python3
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.log_config import get_logger
logger = get_logger("gen_stock_names", "gen_stock_names.log")
"""更新股票中文名表"""
import tushare as ts
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
pro = ts.pro_api()
df = pro.stock_basic(list_status='L', fields='ts_code,name')
names = dict(zip(df['ts_code'], df['name']))
out_path = PROJECT_ROOT / 'frontend' / 'stock_names.json'
with open(out_path, 'w', encoding='utf-8') as f:
    json.dump(names, f, ensure_ascii=False)
print(f'更新了 {len(names)} 只股票的中文名')
