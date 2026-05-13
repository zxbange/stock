#!/usr/bin/env python3
"""
ETF数据下载 - 首选Tushare，备用Sina+Baostock
- 主数据源: Tushare (fund_daily + fund_adj)
- 备用数据源: Baostock(ETF列表) + Sina(历史K线)
- 增量逻辑: 已有CSV则从最后一天增量，否则全量下载
- Sina volume: 股转手(÷100)，amount ≈ vol×close÷10
- 复权因子: Sina固定1.0
"""
from __future__ import annotations

import logging
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import pandas as pd
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.log_config import get_logger
logger = get_logger("下载ETF数据")

PROJECT_ROOT = Path(__file__).parent.parent.parent

# ---------- 常量 ----------
DATA_DIR = PROJECT_ROOT / "data/etf"
MAX_WORKERS = 4
START_DATE = "20140101"
END_DATE   = datetime.now().strftime("%Y%m%d")

# ---------- Tushare ----------
_TUSHARE_TOKEN = "34ffa547652d6ddcc3b8ace33adb97f6f582656a02599a059091c705"

def get_tushare_api():
    import tushare as ts
    ts.set_token(_TUSHARE_TOKEN)
    return ts.pro_api(timeout=60)

# ---------- Rate Limiter ----------
_lock = threading.Lock()
_last_call = 0.0

def rate_call(func, **kwargs):
    """限速: 每次调用间隔 >0.2秒"""
    global _last_call
    with _lock:
        now = time.time()
        elapsed = now - _last_call
        if elapsed < 0.2:
            time.sleep(0.2 - elapsed)
        _last_call = time.time()
    return func(**kwargs)


# ============================================================
# 数据源A: Tushare - 获取ETF列表
# ============================================================
def get_etf_list_tushare() -> pd.DataFrame:
    """从Tushare获取ETF列表（不限制status，获取全部在市ETF）"""
    api = get_tushare_api()
    df = api.fund_basic(
        market="E",
        fields="ts_code,name,benchmark,found_date",
    )
    df["found_date"] = df["found_date"].astype(str)
    # 下载全部ETF，不限制成立时间
    df = df.copy()
    logger.info("Tushare ETF列表（含LOF）: %d 只", len(df))
    return df


# ============================================================
# 数据源A: Tushare - 下载单只ETF原始日K线+复权因子
# ============================================================
def fetch_etf_tushare(code: str, start: str, end: str) -> tuple:
    """下载单只ETF (Tushare原始数据)，返回 (df, adj_df)"""
    api = get_tushare_api()
    df = rate_call(api.fund_daily, ts_code=code, start_date=start, end_date=end)
    if df is None or df.empty:
        return None, None
    adj_df = rate_call(api.fund_adj, ts_code=code)
    if adj_df is None or adj_df.empty:
        return None, None
    return df, adj_df


# ============================================================
# 数据源B: Baostock - 获取ETF列表
# ============================================================
def get_etf_list_baostock() -> pd.DataFrame:
    """从Baostock获取全部ETF代码列表 (sz.15xxx / sh.51xxx)"""
    import baostock as bs
    lg = bs.login()
    rs = bs.query_all_stock(day=datetime.now().strftime("%Y-%m-%d"))
    rows = []
    while rs.error_code == "0" and rs.next():
        rows.append(rs.get_row_data())
    bs.logout()
    df = pd.DataFrame(rows, columns=rs.fields)
    etf_df = df[df["code"].str.match(r"^(sz\.15|sh\.51)")].copy()
    etf_df = etf_df.rename(columns={"code": "bao_code", "code_name": "name"})
    logger.info("Baostock ETF列表: %d 只", len(etf_df))
    return etf_df


# ============================================================
# 数据源B: Sina - 获取单只ETF历史K线
# ============================================================
def fetch_etf_sina(sina_code: str, start_date: str = None) -> pd.DataFrame | None:
    """从Sina获取单只ETF历史K线 (date,open,high,low,close,volume)"""
    import akshare as ak
    try:
        hist = rate_call(ak.fund_etf_hist_sina, symbol=sina_code)
        if hist is None or hist.empty:
            return None
        hist = hist.copy()
        hist.columns = [c.lower() for c in hist.columns]
        if "date" not in hist.columns:
            return None
        if start_date:
            start_dt = pd.to_datetime(start_date).date()
            hist = hist[pd.to_datetime(hist["date"]).dt.date >= start_dt]
        if hist.empty:
            return None
        return hist
    except Exception as e:
        logger.debug("Sina获取失败 %s: %s", sina_code, e)
        return None


# ============================================================
# 工具函数
# ============================================================
def bao_code_to_sina(bao_code: str) -> str:
    """sz.159001 -> sz159001"""
    return bao_code.replace(".", "").lower()

def bao_code_to_tushare(bao_code: str) -> str:
    """sz.159001 -> 159001.SZ  /  sh.510050 -> 510050.SH"""
    code = bao_code.replace(".", "")
    xch = code[:2]
    num = code[2:]
    exchange = ".SZ" if xch == "sz" else ".SH"
    return num + exchange

def enrich_etf_df(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["sina_code"] = df["bao_code"].apply(bao_code_to_sina)
    df["ts_code"]   = df["bao_code"].apply(bao_code_to_tushare)
    return df


# ============================================================
# 增量判断
# ============================================================
def plan_download(ts_code: str, sina_code: str = None) -> tuple | None:
    """返回 (ts_code, sina_code, start, is_full) 或 None(已是最新)"""
    path = DATA_DIR / f"{ts_code}.csv"
    if path.exists() and path.stat().st_size > 100:
        try:
            existing = pd.read_csv(path, usecols=["date"], parse_dates=["date"])
            last_date = existing["date"].max().strftime("%Y-%m-%d")
            today_str = datetime.now().strftime("%Y-%m-%d")
            if last_date >= today_str:
                return None
            next_day = (pd.to_datetime(last_date) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
            return (ts_code, sina_code, next_day, False)
        except Exception:
            pass
    return (ts_code, sina_code, "2014-01-01", True)


# ============================================================
# 保存ETF数据
# ============================================================
def save_etf_data(ts_code: str, df: pd.DataFrame, is_sina: bool = False):
    """
    将 df 保存到 DATA_DIR/ts_code.csv
    is_sina=True: 需做 volume÷100、amount=vol×close÷10、adj_factor=1.0
    """
    path = DATA_DIR / f"{ts_code}.csv"
    df = df.copy()

    if is_sina:
        # date列转换
        df["date"] = pd.to_datetime(df["date"])
        # volume: Sina原始是股，转为手
        if "volume" in df.columns:
            df["volume"] = (df["volume"] / 100).round(2)
        # adj_factor = 1.0
        df["adj_factor"] = 1.0
        # amount ≈ vol(手) × close ÷ 10
        if "amount" not in df.columns or all(df["amount"].isna()):
            df["amount"] = (df["volume"] * df["close"] / 10).round(2)
        # pre_close / change / pct_chg
        df["pre_close"] = df["close"].shift(1)
        df["change"]    = df["close"] - df["pre_close"]
        df["pct_chg"]   = (df["change"] / df["pre_close"] * 100).round(2)
        # ts_code 列
        df.insert(0, "ts_code", ts_code)
    else:
        # Tushare: trade_date→date, vol→volume, adj_factor=1.0
        if "trade_date" in df.columns:
            df["date"] = pd.to_datetime(df["trade_date"].astype(str))
            df = df.drop(columns=["trade_date"])
        if "vol" in df.columns:
            df["volume"] = df.pop("vol")
        df["adj_factor"] = 1.0

    df = df.sort_values("date").reset_index(drop=True)

    keep_cols = ["ts_code", "date", "pre_close", "open", "high", "low",
                 "close", "change", "pct_chg", "volume", "amount", "adj_factor"]
    df = df[[c for c in keep_cols if c in df.columns]]

    if path.exists() and path.stat().st_size > 100:
        try:
            existing = pd.read_csv(path, parse_dates=["date"])
            df = pd.concat([existing, df], ignore_index=True)
            df = df.drop_duplicates(subset=["date"]).sort_values("date").reset_index(drop=True)
        except Exception as e:
            logger.warning("合并 %s 失败，重新写入: %s", ts_code, e)

    df.to_csv(path, index=False, encoding="utf-8")


# ============================================================
# 主流程
# ============================================================
def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    logger.info("=" * 60)
    logger.info("ETF数据下载任务（首选Tushare，备用Sina+Baostock）")
    logger.info("当前时间: %s", now.strftime("%Y-%m-%d %H:%M"))
    logger.info("数据目录: %s", DATA_DIR)
    logger.info("=" * 60)

    # ---------- 步骤1: 尝试Tushare ----------
    tushare_ok = False
    etf_df = None
    try:
        logger.info("尝试Tushare数据源...")
        etf_df = get_etf_list_tushare()
        tushare_ok = True
        logger.info("Tushare可用 ✅")
    except Exception as e:
        logger.warning("Tushare失败，切换备用数据源: %s", e)

    if tushare_ok:
        # ---------- Tushare模式 ----------
        all_codes = etf_df["ts_code"].tolist()
        logger.info("需下载ETF总数: %d 只", len(all_codes))

        # 增量判断
        download_plan = []
        for code in all_codes:
            plan = plan_download(code)
            if plan:
                download_plan.append(plan)

        todo_full = sum(1 for _, _, _, is_full in download_plan if is_full)
        todo_inc  = sum(1 for _, _, _, is_full in download_plan if not is_full)
        logger.info("需下载: %d 只（全量%d，增量%d）", len(download_plan), todo_full, todo_inc)

        if not download_plan:
            logger.info("全部ETF已是最新，无需下载")
            return

        success, fail = 0, 0
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
            futures = {ex.submit(fetch_etf_tushare, code, start, END_DATE): (code, start)
                       for code, _, start, is_full in download_plan}
            for fut in tqdm(as_completed(futures), total=len(futures), desc="Tushare下载", leave=True):
                code, start = futures[fut]
                try:
                    df, adj_df = fut.result()
                    if df is not None and adj_df is not None:
                        save_etf_data(code, df, is_sina=False)
                        success += 1
                    else:
                        fail += 1
                except Exception as e:
                    logger.error("处理 %s 失败: %s", code, e)
                    fail += 1

        logger.info("Tushare下载完成: 成功%d，失败%d", success, fail)

    else:
        # ---------- 备用Sina+Baostock模式 ----------
        logger.info("使用备用数据源: Baostock+Sina")
        etf_df = get_etf_list_baostock()
        etf_df = enrich_etf_df(etf_df)
        all_records = etf_df[["bao_code", "sina_code", "ts_code"]].to_dict("records")
        logger.info("ETF总数: %d 只", len(all_records))

        # 增量判断（基于Sina代码）
        download_plan = []
        for row in all_records:
            plan = plan_download(row["ts_code"], row["sina_code"])
            if plan:
                download_plan.append(plan)

        todo_full = sum(1 for _, _, _, is_full in download_plan if is_full)
        todo_inc  = sum(1 for _, _, _, is_full in download_plan if not is_full)
        logger.info("需下载: %d 只（全量%d，增量%d）", len(download_plan), todo_full, todo_inc)

        if not download_plan:
            logger.info("全部ETF已是最新，无需下载")
            return

        def download_one(item):
            _, sina_code, start, is_full = item
            df = fetch_etf_sina(sina_code, start)
            return sina_code, df, is_full

        success, fail = 0, 0
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
            futures = {ex.submit(download_one, item): item for item in download_plan}
            for fut in tqdm(as_completed(futures), total=len(futures), desc="Sina下载", leave=True):
                item = futures[fut]
                try:
                    sina_code, df, is_full = fut.result()
                    if df is not None and not df.empty:
                        ts_code = item[0]
                        save_etf_data(ts_code, df, is_sina=True)
                        success += 1
                    else:
                        fail += 1
                except Exception as e:
                    logger.error("处理 %s 失败: %s", item[0], e)
                    fail += 1

        logger.info("Sina下载完成: 成功%d，失败%d", success, fail)

    # 保存ETF列表
    list_path = DATA_DIR / "etf_list.csv"
    if etf_df is not None:
        etf_df.to_csv(list_path, index=False, encoding="utf-8")
        logger.info("ETF列表已保存: %s", list_path)


if __name__ == "__main__":
    main()
