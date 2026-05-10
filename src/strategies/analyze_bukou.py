#!/usr/bin/env python3
"""
补票战法选股（完全独立，无外部依赖）
参数（硬编码，匹配configs.json）：
- n_short: 3, n_long: 21, m: 3
- bbi_min_window: 2, max_window: 60, bbi_q_threshold: 0.2
"""

import sys, logging
from pathlib import Path
from typing import Dict, List
import pandas as pd
import numpy as np

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


# ---- 指标计算（来自原Selector.py）----
def compute_bbi(df):
    ma3 = df["close"].rolling(3).mean()
    ma6 = df["close"].rolling(6).mean()
    ma12 = df["close"].rolling(12).mean()
    ma24 = df["close"].rolling(24).mean()
    return (ma3 + ma6 + ma12 + ma24) / 4


def compute_rsv(df, n):
    low_n = df["low"].rolling(window=n, min_periods=1).min()
    high_close_n = df["close"].rolling(window=n, min_periods=1).max()
    return (df["close"] - low_n) / (high_close_n - low_n + 1e-9) * 100.0


def compute_dif(df, fast=12, slow=26):
    ema_fast = df["close"].ewm(span=fast, adjust=False).mean()
    ema_slow = df["close"].ewm(span=slow, adjust=False).mean()
    return ema_fast - ema_slow


def bbi_deriv_uptrend(bbi, *, min_window, max_window=None, q_threshold=0.0):
    """BBI整体上升判断（原Selector.py逻辑）"""
    bbi = bbi.dropna()
    if len(bbi) < min_window:
        return False
    longest = min(len(bbi), max_window or len(bbi))
    for w in range(longest, min_window - 1, -1):
        seg = bbi.iloc[-w:]
        norm = seg / seg.iloc[0]
        diffs = np.diff(norm.values)
        if np.quantile(diffs, q_threshold) >= 0:
            return True
    return False


class BBIShortLongSelector:
    def __init__(self, n_short=3, n_long=21, m=3,
                 bbi_min_window=2, max_window=60, bbi_q_threshold=0.2):
        if m < 2:
            raise ValueError("m must be >= 2")
        self.n_short = n_short
        self.n_long = n_long
        self.m = m
        self.bbi_min_window = bbi_min_window
        self.max_window = max_window
        self.bbi_q_threshold = bbi_q_threshold

    def _passes_filters(self, hist):
        hist = hist.copy()
        hist["BBI"] = compute_bbi(hist)
        if not bbi_deriv_uptrend(
            hist["BBI"],
            min_window=self.bbi_min_window,
            max_window=self.max_window,
            q_threshold=self.bbi_q_threshold,
        ):
            return False
        hist["RSV_short"] = compute_rsv(hist, self.n_short)
        hist["RSV_long"] = compute_rsv(hist, self.n_long)
        if len(hist) < self.m:
            return False
        win = hist.iloc[-self.m:]
        long_ok = (win["RSV_long"] >= 80).all()
        short_series = win["RSV_short"]
        short_ok = (short_series.iloc[0] >= 80 and short_series.iloc[-1] >= 80
                    and (short_series < 20).any())
        if not (long_ok and short_ok):
            return False
        hist["DIF"] = compute_dif(hist)
        return hist["DIF"].iloc[-1] > 0

    def select(self, date, data):
        picks = []
        for code, df in data.items():
            hist = df[df["date"] <= date]
            if hist.empty:
                continue
            need_len = (max(self.n_short, self.n_long)
                        + self.bbi_min_window + self.m)
            hist = hist.tail(max(need_len, self.max_window))
            if self._passes_filters(hist):
                picks.append(code)
        return picks


def main():
    import argparse
    parser = argparse.ArgumentParser(description="补票战法选股")
    parser.add_argument("--data-dir", default="./data_kline", help="CSV目录")
    parser.add_argument("--date", help="交易日 YYYY-MM-DD")
    parser.add_argument("--tickers", default="all", help="'all'或逗号列表")
    parser.add_argument("--log", default="./log/select_results.log", help="日志文件")
    parser.add_argument("--out-dir", help="输出目录，保存结果txt")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    tickers = args.tickers.split(',') if args.tickers != 'all' else None
    date = pd.Timestamp(args.date) if args.date else None

    data = {}
    for csv_path in sorted(data_dir.glob("*.csv")):
        code = csv_path.stem
        if tickers and code not in tickers:
            continue
        df = pd.read_csv(csv_path, parse_dates=["date"])
        data[code] = df

    if not data:
        logger.warning("没有加载任何数据")
        return

    if date is None:
        date = max(df["date"].max() for df in data.values())
    logger.info("交易日: %s", date.strftime("%Y-%m-%d"))

    selector = BBIShortLongSelector()
    picks = selector.select(date, data)

    alias = "补票战法"
    with open(args.log, "a", encoding="utf-8") as f:
        f.write(f"\n{'='*20} 选股结果 [{alias}] {'='*20}\n")
        f.write(f"交易日: {date.strftime('%Y-%m-%d')}\n")
        f.write(f"符合条件股票数: {len(picks)}\n")
        if picks:
            f.write("股票代码: " + ", ".join(picks) + "\n")
            for code in picks:
                f.write(f"  {code}\n")
        else:
            f.write("无符合条件股票\n")
        f.write("\n")

    # 保存结果到txt（供后续流程读取）
    if args.out_dir:
        out_path = Path(args.out_dir) / f"result_{alias.replace('战法','')}.txt"
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(alias + "\n")
            for code in picks:
                f.write(code + "\n")

    logger.info("选股完成: %s", f"符合{len(picks)}只" if picks else "无结果")


if __name__ == "__main__":
    main()