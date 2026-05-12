#!/usr/bin/env python3
"""
填坑战法选股（完全独立，无外部依赖）
参数（硬编码，匹配configs.json）：
- j_threshold: 10, max_window: 100, fluc_threshold: 0.03
- gap_threshold: 0.2, j_q_threshold: 0.10
"""

import sys, logging
from pathlib import Path
from typing import Dict, List
import pandas as pd
import numpy as np
from scipy.signal import find_peaks

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


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


def _find_peaks(df, *, column="high", distance=None, prominence=None,
                height=None, width=None, rel_height=0.5, **kwargs):
    if column not in df.columns:
        raise KeyError(f"'{column}' not found in columns")
    y = df[column].to_numpy()
    indices, props = find_peaks(y, distance=distance, prominence=prominence,
                               height=height, width=width, rel_height=rel_height, **kwargs)
    peaks_df = df.iloc[indices].copy()
    peaks_df["is_peak"] = True
    for key, arr in props.items():
        if isinstance(arr, (list, np.ndarray)) and len(arr) == len(indices):
            peaks_df[f"peak_{key}"] = arr
    return peaks_df


class PeakKDJSelector:
    def __init__(self, j_threshold=10, max_window=100, fluc_threshold=0.03,
                 gap_threshold=0.2, j_q_threshold=0.10):
        self.j_threshold = j_threshold
        self.max_window = max_window
        self.fluc_threshold = fluc_threshold
        self.gap_threshold = gap_threshold
        self.j_q_threshold = j_q_threshold

    def _passes_filters(self, hist):
        if hist.empty:
            return False
        hist = hist.copy().sort_values("date")
        hist["oc_max"] = hist[["open", "close"]].max(axis=1)

        peaks_df = _find_peaks(hist, column="oc_max", distance=6, prominence=0.5)
        date_today = hist.iloc[-1]["date"]
        peaks_df = peaks_df[peaks_df["date"] < date_today]
        if len(peaks_df) < 2:
            return False

        peak_t = peaks_df.iloc[-1]
        peaks_list = peaks_df.reset_index(drop=True)
        oc_t = peak_t.oc_max
        total_peaks = len(peaks_list)

        target_peak = None
        for idx in range(total_peaks - 2, -1, -1):
            peak_prev = peaks_list.loc[idx]
            oc_prev = peak_prev.oc_max
            if oc_t <= oc_prev:
                continue
            if total_peaks >= 3 and idx < total_peaks - 2:
                inter_oc = peaks_list.loc[idx + 1 : total_peaks - 2, "oc_max"]
                if not (inter_oc < oc_prev).all():
                    continue
            date_prev = peak_prev.date
            mask = (hist["date"] > date_prev) & (hist["date"] < peak_t.date)
            min_close = hist.loc[mask, "close"].min()
            if pd.isna(min_close):
                continue
            if oc_prev <= min_close * (1 + self.gap_threshold):
                continue
            target_peak = peak_prev
            break

        if target_peak is None:
            return False

        close_today = hist.iloc[-1]["close"]
        fluc_pct = abs(close_today - target_peak.close) / target_peak.close
        if fluc_pct > self.fluc_threshold:
            return False

        kdj = compute_kdj(hist)
        j_today = float(kdj.iloc[-1]["J"])
        j_window = kdj["J"].tail(self.max_window).dropna()
        if j_window.empty:
            return False
        j_quantile = float(j_window.quantile(self.j_q_threshold))
        if not (j_today < self.j_threshold or j_today <= j_quantile):
            return False

        return True

    def select(self, date, data):
        picks = []
        for code, df in data.items():
            hist = df[df["date"] <= date]
            if hist.empty:
                continue
            hist = hist.tail(self.max_window)
            if self._passes_filters(hist):
                picks.append(code)
        return picks


def main():
    import argparse
    parser = argparse.ArgumentParser(description="填坑战法选股")
    parser.add_argument("--data-dir", default=str(PROJECT_ROOT / "data/kline"), help="CSV目录")
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

    selector = PeakKDJSelector()
    picks = selector.select(date, data)

    alias = "填坑战法"
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
        out_path = Path(args.out_dir) / "result_填坑.txt"
        with open(out_path, "w", encoding="utf-8") as f:
            f.write("填坑战法" + "\n")
            for code in picks:
                f.write(code + "\n")


    logger.info("选股完成: %s", f"符合{len(picks)}只" if picks else "无结果")


if __name__ == "__main__":
    main()