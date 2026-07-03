#!/usr/bin/env python3
"""生成通知文件 - 从today/result_*.txt读取"""
from pathlib import Path
import re
import sys
from datetime import date

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
from utils.log_config import get_logger
logger = get_logger("生成通知")

today_dir = PROJECT_ROOT / 'daily_result' / 'today'
files = {
    '补票': today_dir / 'result_补票.txt',
    'TePu': today_dir / 'result_回头.txt',
    '填坑': today_dir / 'result_填坑.txt',
    '大波浪': today_dir / 'result_大波.txt',
    '红悬停': today_dir / 'result_跳高.txt',
    '蓄力': today_dir / 'result_蓄力.txt',
    '高业绩': today_dir / 'result_实力.txt',
}

data = {}
for name, fpath in files.items():
    if fpath.exists():
        with open(fpath) as f:
            lines = [l.strip() for l in f if l.strip()]
        data[name] = [l for l in lines if re.match(r'^\d{6}\.(?:SZ|SH|BJ)$', l)]
    else:
        data[name] = []

total = sum(len(v) for v in data.values())
today_str = date.today().strftime('%Y-%m-%d')

logger.info("各战法读取结果: 补票=%d, TePu=%d, 填坑=%d, 红悬停=%d, 大波浪=%d, 蓄力=%d, 高业绩=%d",
            len(data['补票']), len(data['TePu']), len(data['填坑']),
            len(data['红悬停']), len(data['大波浪']), len(data['蓄力']), len(data['高业绩']))

msg_parts = []
msg_parts.append(" STOCKRESULT")
msg_parts.append("DATE: " + today_str)
msg_parts.append("BUKOU_COUNT: " + str(len(data['补票'])))
msg_parts.append("BUKOU: " + ",".join(data['补票']))
msg_parts.append("TEPOU_COUNT: " + str(len(data['TePu'])))
msg_parts.append("TEPOU: " + ",".join(data['TePu']))
msg_parts.append("TIANKENG_COUNT: " + str(len(data['填坑'])))
tk_codes = data['填坑']
msg_parts.append("TIANKENG: " + ",".join(tk_codes[:10]) + ("..." if len(tk_codes) > 10 else ""))
msg_parts.append("HONGXUANTI_COUNT: " + str(len(data['红悬停'])))
msg_parts.append("HONGXUANTI: " + ",".join(data['红悬停']))
msg_parts.append("DABOLANG_COUNT: " + str(len(data['大波浪'])))
db_codes = data['大波浪']
msg_parts.append("DABOLANG: " + ",".join(db_codes[:10]) + ("..." if len(db_codes) > 10 else ""))
msg_parts.append("XULILONG_COUNT: " + str(len(data['蓄力'])))
msg_parts.append("XULILONG: " + ",".join(data['蓄力']))
msg_parts.append("YJZZ_COUNT: " + str(len(data['高业绩'])))
msg_parts.append("YJZZ: " + ",".join(data['高业绩']))
msg_parts.append("TOTAL: " + str(total))

msg = "\n".join(msg_parts)

Path('/tmp/stock_notifications').mkdir(parents=True, exist_ok=True)
with open('/tmp/stock_notifications/stock_daily_result.txt', 'w') as f:
    f.write(msg)

logger.info("通知文件已写入，共 %d 只股票", total)