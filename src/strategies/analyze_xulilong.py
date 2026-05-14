#!/usr/bin/env python3
"""
蓄力龙选股分析脚本

选股逻辑（三阳蓄力形态）：
1. T-2日：阳线（收>开），涨幅>3%，成交量>T-3日×1.2
2. T-1日：阴线（收<开），收盘>T-2开盘，跌幅<-4%，成交量<T-2日×0.8
3. T日：  阳线（收>开），收盘>T-2收盘，涨幅>3%，成交量>T-1日×1.2
4. 均线： MA10 > MA20 > MA30 > MA60
"""

from __future__ import annotations

import glob
import sys
from pathlib import Path

import pandas as pd

# ---------- 日志（统一标准格式） ----------
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
from utils.log_config import get_logger
logger = get_logger("蓄力龙")

# ---------- 配置 ----------
DATA_DIR = PROJECT_ROOT / "data/kline"
OUT_DIR = PROJECT_ROOT / "daily_result/today"

# 条件参数
RISE_THRESHOLD = 3.0   # 涨幅阈值（%）
FALL_THRESHOLD = -4.0  # 跌幅上限（%）
VOLUME_ENLARGE_T2 = 1.2  # T-2日放量倍数
VOLUME_SHRINK_T1 = 0.8   # T-1日缩量倍数
VOLUME_ENLARGE_T = 1.2   # T日放量倍数


def analyze_one(code: str, df: pd.DataFrame) -> bool:
    """
    分析单只股票是否满足蓄力龙条件
    df: 按date升序排列的日K线数据（最后一行=T日）
    需要至少65个交易日（算MA60）
    """
    if df is None or len(df) < 65:
        return False

    # 取最近65个交易日
    df = df.tail(65).copy().reset_index(drop=True)

    if len(df) < 5:
        return False

    day_t3  = df.iloc[-4]  # T-3
    day_t2  = df.iloc[-3]  # T-2
    day_t1  = df.iloc[-2]  # T-1
    day_t   = df.iloc[-1]  # T

    # ---- 条件1: T-2日阳线 + 涨幅 > 3% + 放量 ----
    t2_pct   = float(day_t2['pct_chg'])
    t2_open  = float(day_t2['open'])
    t2_close = float(day_t2['close'])
    t2_vol   = float(day_t2['volume'])
    t3_vol   = float(day_t3['volume'])

    cond1_ok = (
        t2_close > t2_open and                          # 阳线
        t2_pct > RISE_THRESHOLD and                     # 涨幅>3%
        t2_vol > t3_vol * VOLUME_ENLARGE_T2            # 放量>1.2倍
    )

    # ---- 条件2: T-1日阴线 + 收盘>T-2开盘 + 跌幅<4% + 缩量 ----
    t1_pct   = float(day_t1['pct_chg'])
    t1_open  = float(day_t1['open'])
    t1_close = float(day_t1['close'])
    t1_vol   = float(day_t1['volume'])

    cond2_ok = (
        t1_close < t1_open and                           # 阴线（收<开）
        t1_close > t2_open and                            # 收盘>T-2开盘价
        -4.0 < t1_pct < 0 and                             # 跌幅低于4%（-4% < 跌幅 < 0）
        t1_vol < t2_vol * VOLUME_SHRINK_T1               # 缩量<0.8倍
    )

    # ---- 条件3: T日阳线 + 收盘>T-2收盘 + 涨幅>3% + 放量 ----
    t_pct   = float(day_t['pct_chg'])
    t_open  = float(day_t['open'])
    t_close = float(day_t['close'])
    t_vol   = float(day_t['volume'])

    cond3_ok = (
        t_close > t_open and                            # 阳线
        t_close > t2_close and                          # 收盘>T-2收盘价
        t_pct > RISE_THRESHOLD and                       # 涨幅>3%
        t_vol > t1_vol * VOLUME_ENLARGE_T               # 放量>1.2倍
    )

    # ---- 条件4: 均线多头（MA10>MA20>MA30>MA60） ----
    closes = df['close'].values.astype(float)
    ma10 = closes[-10:].mean() if len(closes) >= 10 else 0
    ma20 = closes[-20:].mean() if len(closes) >= 20 else 0
    ma30 = closes[-30:].mean() if len(closes) >= 30 else 0
    ma60 = closes[-60:].mean() if len(closes) >= 60 else 0

    cond4_ok = ma10 > ma20 > ma30 > ma60

    return cond1_ok and cond2_ok and cond3_ok and cond4_ok


def main():
    import argparse
    parser = argparse.ArgumentParser(description="蓄力龙选股")
    parser.add_argument("--out-dir", type=str, default=str(OUT_DIR))
    parser.add_argument("--log", default="log/select_results.log", help="日志文件")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    logger.info("=" * 60)
    logger.info("蓄力龙选股开始")
    logger.info("数据目录: %s", DATA_DIR)
    logger.info("条件: 涨幅>3% | 跌幅<-4% | MA10>MA20>MA30>MA60")
    logger.info("=" * 60)

    csv_files = sorted(glob.glob(str(DATA_DIR / "*.csv")))
    logger.info("共 %d 只股票", len(csv_files))

    selected = []

    for csv_path in csv_files:
        code = Path(csv_path).stem  # e.g. "000001.SZ"
        try:
            df = pd.read_csv(csv_path,
                             usecols=["date", "open", "high", "low", "close", "volume", "pct_chg"],
                             parse_dates=["date"])
            if df.empty:
                continue
            df = df.sort_values("date").reset_index(drop=True)

            if analyze_one(code, df):
                last = df.iloc[-1]
                logger.info("✅ %s 蓄力龙: T日收盘=%.2f 涨幅=%.2f%% 成交量=%.0f",
                            code, last['close'], last['pct_chg'], last['volume'])
                selected.append({
                    "code": code,
                    "date": str(last['date'].date()),
                    "close": float(last['close']),
                    "pct_chg": float(last['pct_chg']),
                    "volume": float(last['volume']),
                })
        except Exception as e:
            logger.debug("分析 %s 失败: %s", code, e)

    # 保存结果
    result_path = out_dir / "result_蓄力.txt"
    with open(result_path, "w") as f:
        f.write(f"蓄力龙选股结果 ({len(selected)}只)\n")
        f.write("=" * 60 + "\n")
        if selected:
            df_out = pd.DataFrame(selected)
            df_out = df_out.sort_values("pct_chg", ascending=False)
            for _, row in df_out.iterrows():
                f.write(f"{row['code']} {row['date']} 收盘={row['close']:.2f} 涨幅={row['pct_chg']:.2f}%\n")
        else:
            f.write("今日无符合条件的股票\n")

    logger.info("=" * 60)
    logger.info("蓄力龙选股完成: 入围 %d 只", len(selected))
    logger.info("结果文件: %s", result_path)


if __name__ == "__main__":
    main()