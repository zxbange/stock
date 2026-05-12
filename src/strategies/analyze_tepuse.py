#!/usr/bin/env python3
"""
TePu战法选股（完全独立，无外部依赖）
参数（硬编码，匹配configs.json）：
- j_threshold: 1, up_threshold: 3.0, volume_threshold: 0.6667
- offset: 15, max_window: 60, price_range_pct: 1.0, j_q_threshold: 0.10
"""

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.log_config import get_logger
logger = get_logger("分析选股-TePu龙")
from pathlib import Path
from typing import Dict, List
import pandas as pd
import numpy as np

    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)


def compute_kdj(df, n=9):
    if df.empty:
        return df.assign(K=np.nan, D=np.nan, J=np.nan)
    low_n = df["low"].rolling(window=n, min_periods=1).min()
    high_n = df["high"].rolling(window=n, min_periods=1).max()
    rsv = (df["close"] - low_n) / (high_n - low_n + 1e-9) * 100
    K = np.zeros_like(rsv, dtype=float)
    D = np.zeros_like(rsv, dtype=float)
    for i in range(len(df)):
        if i == 0:
            K[i] = D[i] = 50.0
        else:
            K[i] = 2/3 * K[i-1] + 1/3 * rsv.iloc[i]
            D[i] = 2/3 * D[i-1] + 1/3 * K[i]
    J = 3*K - 2*D
    return df.assign(K=K, D=D, J=J)


def compute_dif(df, fast=12, slow=26):
    ema_fast = df["close"].ewm(span=fast, adjust=False).mean()
    ema_slow = df["close"].ewm(span=slow, adjust=False).mean()
    return ema_fast - ema_slow


class BreakoutVolumeKDJSelector:
    def __init__(self, j_threshold=1, up_threshold=3.0, volume_threshold=2.0/3,
                 offset=15, max_window=60, price_range_pct=1.0, j_q_threshold=0.10):
        self.j_threshold = j_threshold
        self.up_threshold = up_threshold
        self.volume_threshold = volume_threshold
        self.offset = offset
        self.max_window = max_window
        self.price_range_pct = price_range_pct
        self.j_q_threshold = j_q_threshold

    def _passes_filters(self, hist):
        if len(hist) < self.offset + 2:
            return False
        hist = hist.tail(self.max_window).copy()

        high, low = hist["close"].max(), hist["close"].min()
        if low <= 0 or (high / low - 1) > self.price_range_pct:
            return False

        hist = compute_kdj(hist)
        hist["pct_chg"] = hist["close"].pct_change() * 100
        hist["DIF"] = compute_dif(hist)

        j_today = float(hist["J"].iloc[-1])
        j_window = hist["J"].tail(self.max_window).dropna()
        if j_window.empty:
            return False
        j_quantile = float(j_window.quantile(self.j_q_threshold))
        if not (j_today < self.j_threshold or j_today <= j_quantile):
            return False
        if hist["DIF"].iloc[-1] <= 0:
            return False

        n = len(hist)
        wnd_start = max(0, n - self.offset - 1)
        last_idx = n - 1
        for t_idx in range(wnd_start, last_idx):
            row = hist.iloc[t_idx]
            if row["pct_chg"] < self.up_threshold:
                continue
            vol_T = row["volume"]
            if vol_T <= 0:
                continue
            vols_except_T = hist["volume"].drop(index=hist.index[t_idx])
            if not (vols_except_T <= self.volume_threshold * vol_T).all():
                continue
            if row["close"] <= hist["close"].iloc[:t_idx].max():
                continue
            if not (hist["J"].iloc[t_idx:last_idx] > hist["J"].iloc[-1] - 10).all():
                continue
            return True
        return False

    def select(self, date, data):
        picks = []
        for code, df in data.items():
            hist = df[df["date"] <= date]
            if hist.empty:
                continue
            hist = hist.tail(self.max_window + self.offset + 1)
            if self._passes_filters(hist):
                picks.append(code)
        return picks


def main():
    import argparse
    parser = argparse.ArgumentParser(description="TePu战法选股")
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

    selector = BreakoutVolumeKDJSelector()
    picks = selector.select(date, data)

    alias = "TePu战法"
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
        out_path = Path(args.out_dir) / "result_TePu.txt"
        with open(out_path, "w", encoding="utf-8") as f:
            f.write("TePu战法" + "\n")
            for code in picks:
                f.write(code + "\n")


    logger.info("选股完成: %s", f"符合{len(picks)}只" if picks else "无结果")


if __name__ == "__main__":
    main()