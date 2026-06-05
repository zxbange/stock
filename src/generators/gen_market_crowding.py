#!/usr/bin/env python3
"""
A股市场抱团拥挤度计算
- 全量：从2024至今每日计算，输出到 data/market_crowding.csv
- 增量：每日收盘后追加当天数据
拥挤度 = 成交额前5%股票的成交额 / 全市场总成交额 × 100%
"""
import sys, os, re
from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / 'src'))
from utils.log_config import get_logger
logger = get_logger("抱团拥挤度")

DATA_DIR      = PROJECT_ROOT / 'data'
CROWDING_CSV  = DATA_DIR / 'market_crowding.csv'
DATA_DIR.mkdir(exist_ok=True)

import tushare as ts
pro = ts.pro_api()

import time as _time
_RATE_WINDOW = 60.0   # 60秒滑动窗口
_RATE_MAX    = 500    # 最多500次调用
_rate_history = []     # 最近调用时间列表

# ─── 工具函数 ───────────────────────────────────────────────────────────────

def _parse_trade_date(x):
    """统一解析为 YYYYMMDD 字符串"""
    if isinstance(x, (int, float)):
        x = str(int(x))
    x = str(x).strip()
    if re.match(r'^\d{8}$', x):
        return x
    return None

def get_all_trade_dates(start_date='20240101', end_date=None):
    """拉取指定区间全部交易日（去重、排序）"""
    if end_date is None:
        end_date = datetime.now().strftime('%Y%m%d')
    df = pro.trade_cal(start_date=start_date, end_date=end_date,
                       fields='exchange,cal_date,is_open')
    df = df[df['is_open'] == 1]
    dates = sorted(df['cal_date'].tolist())
    logger.info("获取到 %d 个交易日 (%s ~ %s)", len(dates), dates[0], dates[-1])
    return dates

def calc_crowding(trade_date):
    """计算指定交易日的抱团拥挤度，返回 dict 或 None（带500次/分速率限制）"""
    # 速率限制
    now = _time.time()
    _rate_history[:] = [t for t in _rate_history if now - t < _RATE_WINDOW]
    if len(_rate_history) >= _RATE_MAX:
        sleep_sec = _RATE_WINDOW - (now - _rate_history[0]) + 0.5
        if sleep_sec > 0:
            logger.info("触发限速，休眠 %.1f 秒", sleep_sec)
            _time.sleep(sleep_sec)
        _rate_history[:] = [t for t in _rate_history if _time.time() - t < _RATE_WINDOW]
    _rate_history.append(_time.time())

    try:
        df = pro.daily(trade_date=trade_date, fields='ts_code,close,amount')
    except Exception as e:
        logger.warning("获取 %s 数据失败: %s", trade_date, e)
        return None

    if df.empty or 'amount' not in df.columns:
        return None

    total_amount = df['amount'].sum()
    if total_amount <= 0:
        return None

    top5_count = max(1, int(len(df) * 0.05))
    top5 = df.nlargest(top5_count, 'amount')
    top5_amount = top5['amount'].sum()

    return {
        'date':          trade_date,
        'total_stocks':  len(df),
        'top5_count':    top5_count,
        'total_amount':  int(total_amount),
        'top5_amount':   int(top5_amount),
        'crowding_pct':  round(top5_amount / total_amount * 100, 2),
    }

# ─── 全量重建（从2024起） ────────────────────────────────────────────────────

def rebuild():
    """拉取2024至今所有交易日数据，覆盖写入 CSV"""
    logger.info("=== 开始全量重建 2024至今抱团拥挤度 ===")
    dates = get_all_trade_dates('20240101')

    records = []
    for i, d in enumerate(dates):
        rec = calc_crowding(d)
        if rec:
            records.append(rec)
        else:
            logger.warning("跳过 %s（无数据）", d)

        if (i + 1) % 20 == 0:
            logger.info("全量进度: %d / %d", i + 1, len(dates))

    if not records:
        logger.error("全量数据为空，退出")
        return

    out_df = pd.DataFrame(records)
    out_df.to_csv(CROWDING_CSV, index=False, encoding='utf-8')
    logger.info("全量写入完成: %d 天 → %s", len(records), CROWDING_CSV)


# ─── 增量追加（只补今天） ────────────────────────────────────────────────────

def append_today():
    """追加今天（或最后一个未记录的交易日）数据"""
    today = datetime.now().strftime('%Y%m%d')

    if CROWDING_CSV.exists():
        existing = pd.read_csv(CROWDING_CSV, dtype={'date': str})
        recorded = set(existing['date'].astype(str).tolist())
    else:
        recorded = set()

    # 取最近3天内还没记录的日期（允许补数据）
    candidates = []
    for delta in range(0, 4):
        d = (datetime.now() - timedelta(days=delta)).strftime('%Y%m%d')
        candidates.append(d)

    new_dates = [d for d in candidates if d not in recorded]
    if not new_dates:
        logger.info("今日(%s)数据已存在，跳过", today)
        return

    logger.info("增量补入: %s", new_dates)
    records = []
    for d in new_dates:
        rec = calc_crowding(d)
        if rec:
            records.append(rec)
            logger.info("  %s → 拥挤度 %.2f%%", d, rec['crowding_pct'])
        else:
            logger.warning("  %s 计算失败", d)

    if not records:
        return

    out_df = pd.DataFrame(records)
    mode = 'a' if CROWDING_CSV.exists() else 'w'
    out_df.to_csv(CROWDING_CSV, index=False, header=(mode == 'w'), mode=mode, encoding='utf-8')
    logger.info("增量追加完成: %d 天", len(records))


# ─── CLI ───────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='A股抱团拥挤度计算')
    parser.add_argument('--mode', choices=['rebuild', 'append'], default='append',
                        help='rebuild=全量重建2024至今, append=仅追加今天(默认)')
    args = parser.parse_args()

    if args.mode == 'rebuild':
        rebuild()
    else:
        append_today()