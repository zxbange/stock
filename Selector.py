from typing import Dict, List, Optional, Any

from scipy.signal import find_peaks
import numpy as np
import pandas as pd


# --------------------------- 通用指标 --------------------------- #

def compute_kdj(df: pd.DataFrame, n: int = 9) -> pd.DataFrame:
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
            K[i] = 2 / 3 * K[i - 1] + 1 / 3 * rsv.iloc[i]
            D[i] = 2 / 3 * D[i - 1] + 1 / 3 * K[i]
    J = 3 * K - 2 * D
    return df.assign(K=K, D=D, J=J)


def compute_bbi(df: pd.DataFrame) -> pd.Series:
    ma3 = df["close"].rolling(3).mean()
    ma6 = df["close"].rolling(6).mean()
    ma12 = df["close"].rolling(12).mean()
    ma24 = df["close"].rolling(24).mean()
    return (ma3 + ma6 + ma12 + ma24) / 4


def compute_rsv(
    df: pd.DataFrame,
    n: int,
) -> pd.Series:
    low_n = df["low"].rolling(window=n, min_periods=1).min()
    high_close_n = df["close"].rolling(window=n, min_periods=1).max()
    rsv = (df["close"] - low_n) / (high_close_n - low_n + 1e-9) * 100.0
    return rsv


def compute_dif(df: pd.DataFrame, fast: int = 12, slow: int = 26) -> pd.Series:
    ema_fast = df["close"].ewm(span=fast, adjust=False).mean()
    ema_slow = df["close"].ewm(span=slow, adjust=False).mean()
    return ema_fast - ema_slow


def bbi_deriv_uptrend(
    bbi: pd.Series,
    min_window: int = 90,
    max_window: int = 150,
    q_threshold: float = 0.05,
) -> bool:
    """检查BBI是否处于上升趋势。
    判断逻辑：BBI的最小回撤幅度（相对于前期高点）不超过 q_threshold。
    回撤 = 1 - bbi / bbi.rolling(max_window).max()
    """
    if len(bbi) < min_window:
        return False
    bbi = bbi.dropna()
    if len(bbi) < min_window:
        return False
    try:
        peak = bbi.rolling(max(max_window, len(bbi)), min_periods=1).max()
        drawdown = 1 - bbi / (peak + 1e-9)
        return drawdown.iloc[-1] <= q_threshold
    except (IndexError, ZeroDivisionError):
        return False


def compute_j(df: pd.DataFrame, n: int = 9) -> pd.Series:
    low_n = df["low"].rolling(window=n, min_periods=1).min()
    high_n = df["high"].rolling(window=n, min_periods=1).max()
    rsv = (df["close"] - low_n) / (high_n - low_n + 1e-9) * 100
    K = np.zeros_like(rsv, dtype=float)
    D = np.zeros_like(rsv, dtype=float)
    for i in range(len(df)):
        if i == 0:
            K[i] = D[i] = 50.0
        else:
            K[i] = 2 / 3 * K[i - 1] + 1 / 3 * rsv.iloc[i]
            D[i] = 2 / 3 * D[i - 1] + 1 / 3 * K[i]
    J = 3 * K - 2 * D
    return pd.Series(J, index=df.index)


def count_st_in_name(name: str) -> int:
    return name.count("ST") + name.count("st")


# --------------------------- 选股器 --------------------------- #

class BBIKDJSelector:
    """
    条件：
    1. BBI 处于上升趋势（BBI 在均线之上）
    2. 最近 J 值下穿 10（DIF 从下往上金叉后 J 回调到 10 附近），
       随后 J 线开始向上转折
    3. DIF > 0
    """
    def __init__(
        self,
        j_threshold: float = 10,
        bbi_min_window: int = 20,
        max_window: int = 60,
        price_range_pct: float = 1,
        bbi_q_threshold: float = 0.3,
        j_q_threshold: float = 0.10,
    ) -> None:
        self.j_threshold = j_threshold
        self.bbi_min_window = bbi_min_window
        self.max_window = max_window
        self.price_range_pct = price_range_pct
        self.bbi_q_threshold = bbi_q_threshold
        self.j_q_threshold = j_q_threshold

    def _passes_filters(self, hist: pd.DataFrame) -> bool:
        hist = hist.copy()
        hist["BBI"] = compute_bbi(hist)

        if not bbi_deriv_uptrend(
            hist["BBI"],
            min_window=self.bbi_min_window,
            max_window=self.max_window,
            q_threshold=self.bbi_q_threshold,
        ):
            return False

        hist["DIF"] = compute_dif(hist)
        if hist["DIF"].iloc[-1] <= 0:
            return False

        hist["K"] = compute_kdj(hist)["K"]
        hist["J"] = compute_j(hist)

        # 取最近 max_window 天的数据来分析 J 值
        win = hist.tail(self.max_window)
        # 需要至少 self.bbi_min_window 天来检测BBI，加上J值分析
        if len(win) < self.bbi_min_window + 10:
            return False

        # 检测 J 值是否在阈值附近（允许一定的误差）
        threshold = self.j_threshold
        recent_j = win["J"].iloc[-5:]  # 取最近5天
        near_threshold = (recent_j < threshold + 5).any() and (recent_j > threshold - 5).any()
        if not near_threshold:
            return False

        # 检测 J 是否有向上转折的迹象（最近2天 J 值在上升）
        j_vals = win["J"].tail(5).values
        if len(j_vals) < 2:
            return False
        if not (j_vals[-1] > j_vals[-2] or j_vals[-1] > j_vals[-3]):
            return False

        return True

    def select(
        self, date: pd.Timestamp, data: Dict[str, pd.DataFrame]
    ) -> List[str]:
        picks: List[str] = []
        for code, df in data.items():
            hist = df[df["date"] <= date]
            if hist.empty:
                continue
            hist = hist.tail(max(self.max_window, self.bbi_min_window + 10))
            if self._passes_filters(hist):
                picks.append(code)
        return picks


class SuperB1Selector:
    """
    满足 :class:`BBIKDJSelector`。
    再加上近 N 个交易日内，日线级别的 MACD 从负转正（ DIF 从下方穿越零轴），
    且当天（或次日）对应的 KDJ J 值在 10 以下。
    """
    def __init__(
        self,
        lookback_n: int = 10,
        close_vol_pct: float = 0.02,
        price_drop_pct: float = 0.02,
        j_threshold: float = 10,
        j_q_threshold: float = 0.10,
        B1_params: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.lookback_n = lookback_n
        self.close_vol_pct = close_vol_pct
        self.price_drop_pct = price_drop_pct
        self.j_threshold = j_threshold
        self.j_q_threshold = j_q_threshold
        self.B1_params = B1_params or {}
        self._b1 = BBIKDJSelector(**self.B1_params)

    def _passes_filters(self, hist: pd.DataFrame) -> bool:
        if not self._b1._passes_filters(hist):
            return False

        hist = hist.tail(self.lookback_n)
        hist["DIF"] = compute_dif(hist)
        hist["K"] = compute_kdj(hist)["K"]
        hist["J"] = compute_j(hist)

        if hist["DIF"].iloc[-1] <= 0:
            return False

        return True

    def select(
        self,
        date: pd.Timestamp,
        data: Dict[str, pd.DataFrame],
    ) -> List[str]:
        picks: List[str] = []
        for code, df in data.items():
            hist = df[df["date"] <= date]
            if hist.empty:
                continue
            hist = hist.tail(max(self.lookback_n, 200))
            if self._passes_filters(hist):
                picks.append(code)
        return picks


class PeakKDJSelector:
    """
    选股条件：
    1. 前高形成（双峰），第二个峰高于第一个峰
    2. 第一个峰对应当天的最低价高于区间内所有收盘价的最低价的 1.2 倍
    3. 价格回到前高附近（收盘价在前高价格的 3% 以内）
    4. DIF > 0
    5. J < 0（或 J 处于历史低分位）
    """
    def __init__(
        self,
        j_threshold: float = 10,
        max_window: int = 100,
        fluc_threshold: float = 0.03,
        j_q_threshold: float = 0.10,
        gap_threshold: float = 0.2,
    ) -> None:
        self.j_threshold = j_threshold
        self.max_window = max_window
        self.fluc_threshold = fluc_threshold
        self.j_q_threshold = j_q_threshold
        self.gap_threshold = gap_threshold

    def _passes_filters(self, hist: pd.DataFrame) -> bool:
        hist = hist.copy()
        if len(hist) < self.max_window:
            return False
        hist["K"] = compute_kdj(hist)["K"]
        hist["J"] = compute_j(hist)
        hist["DIF"] = compute_dif(hist)

        if hist["DIF"].iloc[-1] <= 0:
            return False

        win = hist.tail(self.max_window)
        close_series = win["close"]

        peaks, _ = find_peaks(close_series.values, distance=5, height=0)
        if len(peaks) < 2:
            return False

        last_two_peaks = peaks[-2:]
        peak1_idx, peak2_idx = last_two_peaks[0], last_two_peaks[1]
        peak1_price = close_series.iloc[peak1_idx]
        peak2_price = close_series.iloc[peak2_idx]

        if not (peak2_price > peak1_price * (1 + self.gap_threshold)):
            return False

        low_in_window = close_series.min()
        if not (close_series.iloc[peak1_idx] >= low_in_window * 1.2):
            return False

        latest_close = close_series.iloc[-1]
        if latest_close < peak2_price * (1 - self.fluc_threshold):
            return False

        cur_j = hist["J"].iloc[-1]
        if cur_j >= self.j_threshold:
            return False

        j_history = hist["J"].dropna()
        if len(j_history) < 10:
            return False
        j_q = np.percentile(j_history, self.j_q_threshold * 100)
        if cur_j >= j_q:
            return False

        return True

    def select(
        self,
        date: pd.Timestamp,
        data: Dict[str, pd.DataFrame],
    ) -> List[str]:
        picks: List[str] = []
        for code, df in data.items():
            hist = df[df["date"] <= date]
            if hist.empty:
                continue
            hist = hist.tail(self.max_window)
            if self._passes_filters(hist):
                picks.append(code)
        return picks


class BBIShortLongSelector:
    """
    BBI 上升 + 短/长期 RSV 条件 + DIF > 0 选股器
    """
    def __init__(
        self,
        n_short: int = 3,
        n_long: int = 21,
        m: int = 3,
        bbi_min_window: int = 90,
        max_window: int = 150,
        bbi_q_threshold: float = 0.05,
    ) -> None:
        if m < 2:
            raise ValueError("m 必须 ≥ 2")
        self.n_short = n_short
        self.n_long = n_long
        self.m = m
        self.bbi_min_window = bbi_min_window
        self.max_window = max_window
        self.bbi_q_threshold = bbi_q_threshold

    def _passes_filters(self, hist: pd.DataFrame) -> bool:
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
        short_start_end_ok = (
            short_series.iloc[0] >= 80 and short_series.iloc[-1] >= 80
        )
        short_has_below_20 = (short_series < 20).any()

        if not (long_ok and short_start_end_ok and short_has_below_20):
            return False

        hist["DIF"] = compute_dif(hist)
        return hist["DIF"].iloc[-1] > 0

    def select(
        self,
        date: pd.Timestamp,
        data: Dict[str, pd.DataFrame],
    ) -> List[str]:
        picks: List[str] = []
        for code, df in data.items():
            hist = df[df["date"] <= date]
            if hist.empty:
                continue
            need_len = (
                max(self.n_short, self.n_long)
                + self.bbi_min_window
                + self.m
            )
            hist = hist.tail(max(need_len, self.max_window))
            if self._passes_filters(hist):
                picks.append(code)
        return picks


class BreakoutVolumeKDJSelector:
    """
    放量突破前高：
    1. 涨幅 >= threshold（如 3%）
    2. 成交量超过近期均量
    3. 价格创历史新高
    4. J 值维持低位（或 < 1）
    5. DIF > 0
    """
    def __init__(
        self,
        j_threshold: float = 1,
        j_q_threshold: float = 0.10,
        up_threshold: float = 3.0,
        volume_threshold: float = 0.6667,
        offset: int = 15,
        max_window: int = 60,
        price_range_pct: float = 1,
    ) -> None:
        self.j_threshold = j_threshold
        self.j_q_threshold = j_q_threshold
        self.up_threshold = up_threshold
        self.volume_threshold = volume_threshold
        self.offset = offset
        self.max_window = max_window
        self.price_range_pct = price_range_pct

    def _passes_filters(self, hist: pd.DataFrame) -> bool:
        if len(hist) < self.offset + self.max_window:
            return False

        hist = hist.copy()
        hist["K"] = compute_kdj(hist)["K"]
        hist["J"] = compute_j(hist)
        hist["DIF"] = compute_dif(hist)

        if hist["DIF"].iloc[-1] <= 0:
            return False

        win = hist.tail(self.max_window)
        close_series = win["close"]

        max_price = close_series.max()
        latest_close = close_series.iloc[-1]
        pct_chg = (latest_close - close_series.iloc[-2]) / close_series.iloc[-2] * 100

        # 价格创历史新高（在 max_window 内）
        if latest_close < max_price * (1 - self.price_range_pct / 100):
            return False

        # 涨幅满足条件
        if pct_chg < self.up_threshold:
            return False

        # 成交量放大
        vol = win["volume"].iloc[-self.offset:]
        avg_vol = vol.iloc[:-1].mean()
        if avg_vol <= 0 or vol.iloc[-1] < avg_vol * self.volume_threshold:
            return False

        # J 值维持低位
        cur_j = hist["J"].iloc[-1]
        if cur_j > self.j_threshold:
            return False
        j_history = hist["J"].dropna()
        if len(j_history) < 10:
            return False
        j_q = np.percentile(j_history, self.j_q_threshold * 100)
        if cur_j >= j_q:
            return False

        return True

    def select(
        self, date: pd.Timestamp, data: Dict[str, pd.DataFrame]
    ) -> List[str]:
        picks: List[str] = []
        for code, df in data.items():
            hist = df[df["date"] <= date]
            if hist.empty:
                continue
            hist = hist.tail(self.max_window + self.offset)
            if self._passes_filters(hist):
                picks.append(code)
        return picks


# --------------------------- 大波浪战法 --------------------------- #
"""
大波浪战法选股器

月线条件：
1. 近3个月月线 M5>M10>M20>M30>M60>M120>M240 多头排列
2. 近3个月每月收盘价 > M30
3. 近3个月总成交量 > 前3个月总成交量 × 1.5

周线条件：
4. 近6周周线 M5>M10>M20>M30>M60>M120>M240 多头排列
5. 近10周每周收盘价 > M30
6. 近10周总成交量 > 前10周总成交量 × 1.5

日线条件：
7. 近10个交易日日线 M5>M10>M20>M30>M60>M120>M240 多头排列
8. 近30个交易日 M30>M60>M120>M240
9. 近5天内出现回踩M5或M10，但收盘未跌破M10
"""

def _volume_ratio(vol_series: pd.Series, n1: int, n2: int) -> float:
    """返回最近n1期总量 / 前n2期总量（若不够数据返回0）"""
    if len(vol_series) < n1 + n2:
        return 0.0
    recent = vol_series.iloc[-n1:].sum()
    prev = vol_series.iloc[-n1 - n2:-n1].sum()
    if prev == 0:
        return 0.0
    return recent / prev


def _ma_chain_ok(row: pd.Series, periods: List[int], prefix: str) -> bool:
    """检查 row 中 M5>M10>M20>... 的多头排列"""
    for i in range(len(periods) - 1):
        p1, p2 = periods[i], periods[i + 1]
        v1 = row.get(f'{prefix}ma{p1}', np.nan)
        v2 = row.get(f'{prefix}ma{p2}', np.nan)
        if pd.isna(v1) or pd.isna(v2):
            return False
        if not (v1 > v2):
            return False
    return True


class BigWaveSelector:
    def __init__(
        self,
        monthly_ok_months: int = 3,
        monthly_vol_ratio: float = 1.5,
        weekly_ok_weeks: int = 6,
        weekly_recent_close_weeks: int = 10,
        weekly_vol_ratio: float = 1.5,
        daily_ok_days: int = 10,
        daily_long_days: int = 30,
        pullback_days: int = 5,
    ) -> None:
        self.monthly_ok_months = monthly_ok_months
        self.monthly_vol_ratio = monthly_vol_ratio
        self.weekly_ok_weeks = weekly_ok_weeks
        self.weekly_recent_close_weeks = weekly_recent_close_weeks
        self.weekly_vol_ratio = weekly_vol_ratio
        self.daily_ok_days = daily_ok_days
        self.daily_long_days = daily_long_days
        self.pullback_days = pullback_days

    def _passes_filters(self, hist: pd.DataFrame) -> bool:
        hist = hist.copy().sort_values('date').reset_index(drop=True)

        # 需要足够数据（约1.5年）
        if len(hist) < 400:
            return False

        # ============ 日线 ============
        for p in [5, 10, 20, 30, 60, 120, 240]:
            hist[f'd_ma{p}'] = hist['close'].rolling(p).mean()

        # 条件7：近10天日线多头排列
        recent10 = hist.tail(self.daily_ok_days)
        periods_d = [5, 10, 20, 30, 60, 120, 240]
        for i in range(len(recent10) - 1):
            row = recent10.iloc[i]
            if not _ma_chain_ok(row, periods_d, 'd_'):
                return False

        # 条件8：近30天 M30>M60>M120>M240
        recent30 = hist.tail(self.daily_long_days)
        long_d = [30, 60, 120, 240]
        for i in range(len(recent30) - 1):
            row = recent30.iloc[i]
            if not _ma_chain_ok(row, long_d, 'd_'):
                return False

        # 条件9：近5天回踩M5或M10，但收盘未跌破M10
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

        # ============ 月线 ============
        hist['month'] = hist['date'].dt.to_period('M')
        monthly = hist.groupby('month').agg(
            open=('open', 'first'),
            high=('high', 'max'),
            low=('low', 'min'),
            close=('close', 'last'),
            volume=('volume', 'sum'),
        ).reset_index()
        monthly = monthly.sort_values('month').reset_index(drop=True)

        for p in [5, 10, 20, 30, 60, 120, 240]:
            monthly[f'm_ma{p}'] = monthly['close'].rolling(p).mean()

        # 条件1：近3个月月线多头排列
        if len(monthly) < self.monthly_ok_months + 5:
            return False
        recent_m = monthly.tail(self.monthly_ok_months)
        periods_m = [5, 10, 20, 30, 60, 120, 240]
        for i in range(len(recent_m) - 1):
            row = recent_m.iloc[i]
            if not _ma_chain_ok(row, periods_m, 'm_'):
                return False

        # 条件1补充：每月收盘 > M30
        for i in range(len(recent_m)):
            row = recent_m.iloc[i]
            if not (row['close'] > row['m_ma30']):
                return False

        # 条件2：近3个月成交量 > 前3个月 × 1.5
        if _volume_ratio(monthly['volume'], self.monthly_ok_months, self.monthly_ok_months) < self.monthly_vol_ratio:
            return False

        # ============ 周线 ============
        hist['week'] = hist['date'].dt.to_period('W')
        weekly = hist.groupby('week').agg(
            open=('open', 'first'),
            high=('high', 'max'),
            low=('low', 'min'),
            close=('close', 'last'),
            volume=('volume', 'sum'),
        ).reset_index()
        weekly = weekly.sort_values('week').reset_index(drop=True)

        for p in [5, 10, 20, 30, 60, 120, 240]:
            weekly[f'w_ma{p}'] = weekly['close'].rolling(p).mean()

        # 条件3：近6周周线多头排列
        if len(weekly) < self.weekly_ok_weeks + 5:
            return False
        recent_w = weekly.tail(self.weekly_ok_weeks)
        periods_w = [5, 10, 20, 30, 60, 120, 240]
        for i in range(len(recent_w) - 1):
            row = recent_w.iloc[i]
            if not _ma_chain_ok(row, periods_w, 'w_'):
                return False

        # 条件4：近10周收盘 > M30
        recent10w = weekly.tail(self.weekly_recent_close_weeks)
        for i in range(len(recent10w)):
            row = recent10w.iloc[i]
            if not (row['close'] > row['w_ma30']):
                return False

        # 条件4补充：近10周成交量 > 前10周 × 1.5
        if _volume_ratio(weekly['volume'], self.weekly_recent_close_weeks, self.weekly_recent_close_weeks) < self.weekly_vol_ratio:
            return False

        return True

    def select(
        self, date: pd.Timestamp, data: Dict[str, pd.DataFrame]
    ) -> List[str]:
        picks: List[str] = []
        for code, df in data.items():
            hist = df[df["date"] <= date].copy()
            if hist.empty or len(hist) < 400:
                continue
            try:
                if self._passes_filters(hist):
                    picks.append(code)
            except Exception:
                continue
        return picks