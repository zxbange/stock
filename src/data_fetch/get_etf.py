#!/usr/bin/env python3
"""
获取全市场ETF历史日K线数据
策略：
  1. 下载所有ETF的fund_daily原始数据 + fund_adj复权因子
  2. 本地筛选：同benchmark只保留成交额最大的那只
  3. CSV存RAW价格（adj_factor列同步保存，供前端实时前复权）
数据来源: Tushare fund_daily (原始价格) + fund_adj (复权因子)
前复权公式（前端执行）: adj_price = raw_price × 当日因子 ÷ 最新因子
存储目录: /home/bange/stock/data_etf/
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

# ---------- 日志 ----------
LOG_PATH = Path("/home/bange/stock/log/etf_download.log")
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_PATH, encoding="utf-8", mode="a"),
    ],
)
logger = logging.getLogger("etf_download")

DATA_DIR = Path("/home/bange/stock/data_etf")
START_DATE = "20240101"
END_DATE = datetime.now().strftime("%Y%m%d")

CALL_INTERVAL = 60.0 / 500   # 500次/分钟
MAX_WORKERS = 8             # 并发下载线程数

_token = None
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


def get_api():
    return ts.pro_api()


def get_trade_date() -> str:
    cal = rate_call(get_api().trade_cal, exchange='SSE', end_date=END_DATE, limit=5)
    cal['cal_date'] = cal['cal_date'].astype(str)
    return cal[cal['is_open'] == 1].sort_values('cal_date').iloc[-1]['cal_date']


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
    """获取2024年前成立的所有ETF代码"""
    api = get_api()
    logger.info("获取ETF列表...")
    etf_df = api.fund_basic(
        market="E", status="L",
        fields="ts_code,name,benchmark,found_date",
    )
    etf_df["found_date"] = etf_df["found_date"].astype(str)
    etf_df = etf_df[etf_df["found_date"] < START_DATE].copy()
    logger.info("2024年前成立的ETF: %d 只", len(etf_df))
    return etf_df


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
    logger.info("候选ETF: %d 只", len(all_codes))

    # 步骤2：下载全部ETF原始数据（fund_daily + fund_adj）
    logger.info("开始下载全部ETF原始数据（%d并发）...", MAX_WORKERS)
    raw_data = {}  # code -> (df, adj_df)
    success, fail = 0, 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(fetch_etf_raw, code): code for code in all_codes}
        for fut in as_completed(futures):
            code = futures[fut]
            result = fut.result()
            if result[0] is not None:
                raw_data[code] = result
                success += 1
            else:
                fail += 1
            if (len(raw_data) + fail) % 100 == 0:
                logger.info("下载进度: 成功%d 失败%d", success, fail)

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
    for code in selected_codes:
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