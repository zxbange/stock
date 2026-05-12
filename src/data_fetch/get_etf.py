#!/usr/bin/env python3
"""
获取全市场ETF历史日K线数据
策略：
  1. 下载所有ETF的fund_daily原始数据 + fund_adj复权因子
  2. 本地筛选：同benchmark只保留成交额最大的那只
  3. CSV存RAW价格（adj_factor列同步保存，供前端实时前复权）
数据来源: Tushare fund_daily (原始价格) + fund_adj (复权因子)
前复权公式（前端执行）: adj_price = raw_price × 当日因子 ÷ 最新因子
存储目录: /home/bange/stock/data/etf/
"""

from __future__ import annotations

import logging
import sys
import time
import threading
from datetime import datetime
from pathlib import Path

import pandas as pd
import tushare as ts
from tqdm import tqdm

# ---------- 日志 ----------
sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.log_config import get_logger
logger = get_logger("下载ETF数据")

PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data/etf"
START_DATE = (datetime.now() - __import__('datetime').timedelta(days=365*2)).strftime('%Y0101')
END_DATE = datetime.now().strftime("%Y%m%d")

CALL_INTERVAL = 60.0 / 500   # 500次/分钟
MAX_WORKERS = 8             # 并发下载线程数

_lock = threading.Lock()
_last_call = 0.0


def rate_call(func, *args, **kwargs):
    """同步限速：确保全局调用频率不超过500次/分钟"""
    global _last_call
    with _lock:
        now = time.time()
        wait = CALL_INTERVAL - (now - _last_call)
        if wait > 0:
            time.sleep(wait)
        _last_call = time.time()
    return func(*args, **kwargs)


def get_token():
    p = Path.home() / ".tushare" / "token.csv"
    if p.exists():
        token = p.read_text().strip().split(",")[-1]
        if token and len(token) > 20:
            return token
    raise RuntimeError("Token文件无效，请检查 ~/.tushare/token.csv")

_token = get_token()
ts.set_token(_token)
logger.info("Token已加载: %s...", _token[:10])

def get_api():
    ts.set_token("34ffa547652d6ddcc3b8ace33adb97f6f582656a02599a059091c705")
    return ts.pro_api()


def get_trade_date() -> str:
    """获取最新交易日（动态），API失败时从本地CSV推断"""
    try:
        cal = rate_call(get_api().trade_cal, exchange='SSE', end_date=END_DATE, limit=10)
        cal['cal_date'] = cal['cal_date'].astype(str)
        open_days = cal[cal['is_open'] == 1].sort_values('cal_date')
        if not open_days.empty:
            return open_days.iloc[-1]['cal_date']
    except Exception as e:
        logger.warning("获取交易日失败: %s，改用本地推断", e)
    # Fallback：从本地CSV推断最新日期
    csvs = sorted(DATA_DIR.glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    if csvs:
        with open(csvs[0]) as f:
            next(f)
            for line in f:
                pass  # 读最后一行
            date = line.split(',')[1][:8]
            logger.info("本地推断最新交易日: %s", date)
            return date
    return END_DATE


# ============================================================
# 复权计算
# ============================================================
def apply_forward_adj(df: pd.DataFrame, latest_factor: float) -> pd.DataFrame:
    """
    前复权公式: 前复权价格 = 原始价格 × 当日复权因子 ÷ 最新复权因子
    """
    price_cols = ["close", "open", "high", "low", "pre_close"]
    for col in price_cols:
        if col in df.columns:
            df[col] = df[col] * df["adj_factor"] / latest_factor
    return df


# ============================================================
# 下载单只ETF（原始数据，未复权）
# ============================================================
def fetch_etf_raw(code: str) -> tuple:
    """下载单只ETF原始日K线和复权因子，返回(df, adj_df)或(None, None)"""
    api = get_api()

    df = rate_call(api.fund_daily, ts_code=code, start_date=START_DATE, end_date=END_DATE)
    if df is None or df.empty:
        return None, None

    adj_df = rate_call(api.fund_adj, ts_code=code)
    if adj_df is None or adj_df.empty:
        return None, None

    return df, adj_df


# ============================================================
# 获取ETF列表
# ============================================================
def get_all_etf_codes() -> list:
    """获取START_DATE之前已成立的ETF（动态，通常为2年前）"""
    api = get_api()
    logger.info("获取ETF列表...")
    etf_df = api.fund_basic(
        market="E", status="L",
        fields="ts_code,name,benchmark,found_date",
    )
    etf_df["found_date"] = etf_df["found_date"].astype(str)
    # 保留START_DATE之前成立的ETF（动态过滤，非写死）
    before_start = etf_df[etf_df["found_date"] < START_DATE].copy()
    logger.info("候选ETF: %d 只（%s前成立）", len(before_start), START_DATE)
    return before_start


# ============================================================
# 主流程
# ============================================================
def main():
    from concurrent.futures import ThreadPoolExecutor, as_completed

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    now = datetime.now()
    logger.info("=" * 60)
    logger.info("ETF数据下载任务 (Tushare fund_daily + fund_adj 前复权)")
    logger.info("当前时间: %s", now.strftime("%Y-%m-%d %H:%M"))
    logger.info("数据区间: %s ~ %s", START_DATE, END_DATE)
    logger.info("存储目录: %s", DATA_DIR)
    logger.info("策略: 下载全部ETF → 本地按benchmark+成交额筛选")
    logger.info("=" * 60)

    trade_date = get_trade_date()
    logger.info("最新交易日: %s", trade_date)

    # 步骤1：获取全部ETF列表
    etf_df = get_all_etf_codes()
    all_codes = etf_df["ts_code"].tolist()
    # 断点续传：跳过已有足够数据的CSV（约2年数据>500行）
    existing = []
    for c in all_codes:
        path = DATA_DIR / f"{c}.csv"
        if path.exists() and sum(1 for _ in open(path)) > 500:
            existing.append(c)
    todo_codes = [c for c in all_codes if c not in existing]
    logger.info("候选ETF: %d 只，已存在%d只，待下载%d只", len(all_codes), len(existing), len(todo_codes))

    # 步骤2：下载全部ETF原始数据（fund_daily + fund_adj）
    logger.info("开始下载全部ETF原始数据（%d并发）...", MAX_WORKERS)
    raw_data = {}  # code -> (df, adj_df)
    success, fail = 0, 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(fetch_etf_raw, code): code for code in todo_codes}
        for fut in tqdm(as_completed(futures), total=len(futures), desc="下载ETF原始数据", leave=True):
            code = futures[fut]
            result = fut.result()
            if result[0] is not None:
                raw_data[code] = result
                success += 1
            else:
                fail += 1

    logger.info("原始数据下载完成: 成功%d 失败%d", success, fail)

    # 步骤3：本地筛选 - 按benchmark分组取成交额最大
    logger.info("开始本地筛选...")

    # 获取最新交易日成交额
    amounts = {}
    for code, (df, adj_df) in raw_data.items():
        try:
            # fund_daily的amount列即为成交额
            latest = df[df["trade_date"] == trade_date]
            if not latest.empty and "amount" in latest.columns:
                amounts[code] = float(latest["amount"].iloc[0])
            else:
                # 取最近一个有成交的日期
                amounts[code] = float(df["amount"].dropna().iloc[-1])
        except Exception:
            amounts[code] = 0.0

    etf_df["amount"] = etf_df["ts_code"].map(amounts)
    etf_df["benchmark"] = etf_df["benchmark"].fillna("未知")

    # 按benchmark分组，取成交额最大
    selected = (
        etf_df[etf_df["ts_code"].isin(raw_data.keys())]
        .groupby("benchmark", group_keys=False)
        .apply(lambda g: g.loc[g["amount"].idxmax()])
        .reset_index(drop=True)
    )
    selected_codes = selected["ts_code"].tolist()
    logger.info("按benchmark分组取最大成交额后: %d 只ETF", len(selected_codes))

    # 步骤4：保存raw价格 + 每行的adj_factor（供前端做前复权）
    logger.info("保存RAW价格（前端实时前复权）...")
    saved = 0
    for code in tqdm(selected_codes, total=len(selected_codes), desc="保存ETF前复权", leave=True):
        df, adj_df = raw_data[code]

        # 合并每行的adj_factor（不改变价格）
        adj_df = adj_df.rename(columns={"trade_date": "trade_date_adj"})
        adj_df["trade_date_adj"] = adj_df["trade_date_adj"].astype(str)
        df["trade_date"] = df["trade_date"].astype(str)
        df = df.merge(adj_df[["trade_date_adj", "adj_factor"]], left_on="trade_date", right_on="trade_date_adj", how="left")

        # 整理列：存raw价格
        df = df.rename(columns={"trade_date": "date", "vol": "volume"})
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)

        keep_cols = ["ts_code", "date", "pre_close", "open", "high", "low", "close", "change", "pct_chg", "volume", "amount", "adj_factor"]
        df = df[[c for c in keep_cols if c in df.columns]]

        out_path = DATA_DIR / f"{code}.csv"
        df.to_csv(out_path, index=False, encoding="utf-8")
        saved += 1
        if saved % 50 == 0:
            logger.info("保存进度: %d/%d", saved, len(selected_codes))

    logger.info("=" * 60)
    logger.info("下载完成！")
    logger.info("  原始下载: %d 只（成功%d 失败%d）", len(all_codes), success, fail)
    logger.info("  筛选后: %d 只ETF（前复权K线已保存）", saved)
    logger.info("  数据目录: %s", DATA_DIR)

    # 保存ETF列表
    list_path = DATA_DIR / "etf_list.csv"
    selected.to_csv(list_path, index=False, encoding="utf-8")
    logger.info("  ETF列表已保存: %s", list_path)


if __name__ == "__main__":
    main()
