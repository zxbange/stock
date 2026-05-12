#!/usr/bin/env python3
"""
大波浪战法选股（完全独立，无外部依赖）
参数（硬编码）：
- monthly_ok_months: 3, monthly_vol_ratio: 1.1
- weekly_ok_weeks: 6, weekly_recent_close_weeks: 10, weekly_vol_ratio: 1.2
- daily_ok_days: 10, daily_long_days: 30, pullback_days: 5
- 月线MA链从MA10开始（MA10>MA20>MA30>MA60>MA120>MA240，不要求MA5>MA10）
- 周线MA链从MA10开始（MA10>MA20>MA30>MA60>MA120>MA240，不要求MA5>MA10）
- 日线MA链从MA10开始（MA10>MA20>MA30>MA60>MA120>MA240，不要求MA5>MA10）
"""

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.log_config import get_logger
logger = get_logger("分析选股-大波浪龙")
from pathlib import Path
from typing import Dict, List
import pandas as pd
import numpy as np

    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)


def _volume_ratio(vol_series, n1, n2):
    if len(vol_series) < n1 + n2:
        return 0.0
    recent = vol_series.iloc[-n1:].sum()
    prev = vol_series.iloc[-n1 - n2:-n1].sum()
    if prev == 0:
        return 0.0
    return recent / prev


def _ma_chain_ok(row, periods, prefix):
    """
    检查均线多头排列：每组(v1, v2)中，只要v2有值就必须满足v1>v2；v2为NaN则跳过。
    返回True当且仅当所有已定义的比较都满足 v1 > v2。
    """
    ok_count = 0
    for i in range(len(periods) - 1):
        p1, p2 = periods[i], periods[i + 1]
        v1 = row.get(f'{prefix}ma{p1}', float('nan'))
        v2 = row.get(f'{prefix}ma{p2}', float('nan'))
        # v2 为 NaN → 跳过这组比较（不参与判断）
        if v2 != v2:
            continue
        # v1 必须有值且 v1 > v2
        if v1 != v1 or v1 <= v2:
            return False
        ok_count += 1
    # 至少要有一组有效的比较
    return ok_count > 0


class BigWaveSelector:
    def __init__(self, monthly_ok_months=3, monthly_vol_ratio=1.1,
                 weekly_ok_weeks=6, weekly_recent_close_weeks=10,
                 weekly_vol_ratio=1.2, daily_ok_days=10,
                 daily_long_days=30, pullback_days=5,
                 min_market_cap=2000000):
        self.monthly_ok_months = monthly_ok_months
        self.monthly_vol_ratio = monthly_vol_ratio
        self.weekly_ok_weeks = weekly_ok_weeks
        self.weekly_recent_close_weeks = weekly_recent_close_weeks
        self.weekly_vol_ratio = weekly_vol_ratio
        self.daily_ok_days = daily_ok_days
        self.daily_long_days = daily_long_days
        self.pullback_days = pullback_days
        self.min_market_cap = min_market_cap  # 万元，300亿=3000000

    def _passes_filters(self, hist):
        hist = hist.copy().sort_values('date').reset_index(drop=True)
        if len(hist) < 400:
            return False

        for p in [5, 10, 20, 30, 60, 120, 240]:
            hist[f'd_ma{p}'] = hist['close'].rolling(p).mean()

        recent10 = hist.tail(self.daily_ok_days)
        periods_d = [10, 20, 30, 60, 120, 240]
        for i in range(len(recent10) - 1):
            if not _ma_chain_ok(recent10.iloc[i], periods_d, 'd_'):
                return False

        recent30 = hist.tail(self.daily_long_days)
        long_d = [30, 60, 120, 240]
        for i in range(len(recent30) - 1):
            if not _ma_chain_ok(recent30.iloc[i], long_d, 'd_'):
                return False

        last5 = hist.tail(self.pullback_days)
        pullback_ok = False
        for i in range(len(last5)):
            row = last5.iloc[i]
            low, close = row['low'], row['close']
            ma5, ma10 = row['d_ma5'], row['d_ma10']
            touched = (low <= ma5) or (low <= ma10)
            above_ma10 = (close > ma10)
            if touched and above_ma10:
                pullback_ok = True
                break
        if not pullback_ok:
            return False

        hist['month'] = hist['date'].dt.to_period('M')
        monthly = hist.groupby('month').agg(
            open=('open', 'first'), high=('high', 'max'),
            low=('low', 'min'), close=('close', 'last'), volume=('volume', 'sum')
        ).reset_index().sort_values('month').reset_index(drop=True)
        for p in [5, 10, 20, 30, 60, 120, 240]:
            monthly[f'm_ma{p}'] = monthly['close'].rolling(p, min_periods=p).mean()

        if len(monthly) < self.monthly_ok_months + 5:
            return False
        recent_m = monthly.tail(self.monthly_ok_months)
        periods_m = [10, 20, 30, 60, 120, 240]
        for i in range(len(recent_m) - 1):
            if not _ma_chain_ok(recent_m.iloc[i], periods_m, 'm_'):
                return False
        for i in range(len(recent_m)):
            v30 = recent_m.iloc[i]['m_ma30']
            if v30 == v30 and not (recent_m.iloc[i]['close'] > v30):
                return False
        if _volume_ratio(monthly['volume'], self.monthly_ok_months, self.monthly_ok_months) < self.monthly_vol_ratio:
            return False

        hist['week'] = hist['date'].dt.to_period('W')
        weekly = hist.groupby('week').agg(
            open=('open', 'first'), high=('high', 'max'),
            low=('low', 'min'), close=('close', 'last'), volume=('volume', 'sum')
        ).reset_index().sort_values('week').reset_index(drop=True)
        for p in [5, 10, 20, 30, 60, 120, 240]:
            weekly[f'w_ma{p}'] = weekly['close'].rolling(p, min_periods=p).mean()

        if len(weekly) < self.weekly_ok_weeks + 5:
            return False
        recent_w = weekly.tail(self.weekly_ok_weeks)
        periods_w = [10, 20, 30, 60, 120, 240]
        for i in range(len(recent_w) - 1):
            if not _ma_chain_ok(recent_w.iloc[i], periods_w, 'w_'):
                return False
        recent10w = weekly.tail(self.weekly_recent_close_weeks)
        for i in range(len(recent10w)):
            v30 = recent10w.iloc[i]['w_ma30']
            if v30 == v30 and not (recent10w.iloc[i]['close'] > v30):
                return False
        if _volume_ratio(weekly['volume'], self.weekly_recent_close_weeks, self.weekly_recent_close_weeks) < self.weekly_vol_ratio:
            return False

        return True

    def select(self, date, data):
        picks = []
        # 获取市值数据
        market_caps = {}
        if self.min_market_cap is not None:
            try:
                import tushare as ts
                pro = ts.pro_api()
                trade_date_str = date.strftime('%Y%m%d')
                mdf = pro.daily_basic(trade_date=trade_date_str, fields='ts_code,circ_mv')
                for _, row in mdf.iterrows():
                    if row['circ_mv'] == row['circ_mv']:  # not NaN
                        market_caps[row['ts_code']] = row['circ_mv']
                logger.info(f"获取市值数据: {len(market_caps)} 只")
            except Exception as e:
                logger.warning(f"获取市值数据失败: {e}")

        for code, df in data.items():
            hist = df[df["date"] <= date].copy()
            if hist.empty or len(hist) < 400:
                continue
            # 市值过滤
            if self.min_market_cap is not None:
                mc = market_caps.get(code)
                if mc is None or mc < self.min_market_cap:
                    continue
            try:
                if self._passes_filters(hist):
                    picks.append(code)
            except Exception:
                continue
        return picks


def main():
    import argparse
    parser = argparse.ArgumentParser(description="大波浪战法选股")
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

    selector = BigWaveSelector()
    picks = selector.select(date, data)

    alias = "大波浪战法"
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
        out_path = Path(args.out_dir) / "result_大波浪.txt"
        with open(out_path, "w", encoding="utf-8") as f:
            f.write("大波浪战法" + "\n")
            for code in picks:
                f.write(code + "\n")


    logger.info("选股完成: %s", f"符合{len(picks)}只" if picks else "无结果")


if __name__ == "__main__":
    main()