#!/usr/bin/env python3
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.log_config import get_logger
logger = get_logger("生成dates.json")
"""生成 dates.json（存于 daily_result/ 根目录，不随 today/ 归档）"""
import json

PROJECT_ROOT = Path(__file__).parent.parent.parent
DR = PROJECT_ROOT / 'daily_result'

# 扫描所有有 result_*.txt 的历史目录
dates = sorted(
    d.name for d in DR.iterdir()
    if d.is_dir() and d.name.isdigit() and len(d.name) == 8
    and d.name != 'today'
    and any(f.name.startswith('result_') for f in d.iterdir())
)

# 输出到 daily_result/dates.json（不是 today/）
out = DR / 'dates.json'
with open(out, 'w', encoding='utf-8') as f:
    json.dump(dates, f, ensure_ascii=False)

print(f'dates.json: {len(dates)} 天历史目录 → {out}')
