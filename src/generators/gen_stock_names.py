#!/usr/bin/env python3
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.log_config import get_logger
logger = get_logger("更新中文名表")
"""更新股票中文名表"""
import tushare as ts
import json

PROJECT_ROOT = Path(__file__).parent.parent.parent
pro = ts.pro_api()
df = pro.stock_basic(list_status='L', fields='ts_code,name')
names = dict(zip(df['ts_code'], df['name']))
out_path = PROJECT_ROOT / 'frontend' / 'stock_names.json'
with open(out_path, 'w', encoding='utf-8') as f:
    json.dump(names, f, ensure_ascii=False)
logger.info('更新了 %d 只股票的中文名', len(names))
