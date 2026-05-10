#!/usr/bin/env python3
"""
获取全市场ETF历史日K线数据
策略：同类型（benchmark相同）的ETF只保留成交额最大的那只
数据来源: Tushare fund_daily
存储目录: /home/bange/stock/data_etf/
"""

from __future__ import annotations

import asyncio
import aiohttp
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
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
    ],
)
logger = logging.getLogger("etf_download")

DATA_DIR = Path("/home/bange/stock/data_etf")
START_DATE = "20240101"
END_DATE = datetime.now().strftime("%Y%m%d")

CALL_INTERVAL = 60.0 / 200   # Tushare免费接口约200次/分钟
MAX_CONCURRENCY = 3            # asyncio并发数（太多会触发Tushare限速）
MAX_WORKERS = 20              # 下载阶段线程并发数

_token = None
_lock = threading.Lock()
_last_call = 0.0


def get_token():
    global _token
    if _token is None:
        _token = ts.get_token()   # 返回字符串token，不要用 ts_token (是partial对象)
    return _token


def rate_call(func, *args, **kwargs):
    """同步限速（下载阶段用）"""
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
    cal = get_api().trade_cal(exchange='SSE', end_date=END_DATE, limit=5)
    cal['cal_date'] = cal['cal_date'].astype(str)
    return cal[cal['is_open'] == 1].iloc[-1]['cal_date']


# ============================================================
# 步骤1：asyncio并发获取每只ETF最新成交额
# ============================================================
async def fetch_etf_amount(session, sem, code: str) -> tuple:
    """获取单只ETF指定交易日成交额"""
    payload = {
        "api_name": "fund_daily",
        "token": get_token(),
        "params": {"ts_code": code, "trade_date": ""},
        "fields": "ts_code,amount",
    }
    async with sem:
        try:
            async with session.post(
                "http://api.tushare.pro",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                data = await resp.json()
                items = data.get("data", {}).get("items", [])
                if items:
                    return code, float(items[0][1])
        except Exception:
            pass
    return code, 0.0


async def get_etf_amounts_async(codes: list, trade_date: str) -> dict:
    """并发获取所有ETF最新成交额（asyncio+aiohttp）"""
    sem = asyncio.Semaphore(MAX_CONCURRENCY)
    token = get_token()

    async def fetch_one(code: str):
        payload = {
            "api_name": "fund_daily",
            "token": token,
            "params": {"ts_code": code, "trade_date": trade_date},
            "fields": "ts_code,amount",
        }
        async with sem:
            try:
                # 每请求独立session，避免共享连接问题
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        "http://api.tushare.pro",
                        json=payload,
                        timeout=aiohttp.ClientTimeout(total=15),
                    ) as resp:
                        data = await resp.json()
                        items = data.get("data", {}).get("items", [])
                        if items:
                            return code, float(items[0][1])
            except Exception:
                pass
        return code, 0.0

    tasks = [fetch_one(code) for code in codes]
    results = await asyncio.gather(*tasks)
    return dict(results)


# ============================================================
# 步骤2：筛选同benchmark成交额最大ETF + 下载K线
# ============================================================
def get_etf_list_with_amount(trade_date: str) -> pd.DataFrame:
    """获取ETF列表 + 最新成交额，按benchmark分组取最大"""
    api = get_api()
    logger.info("获取ETF列表...")
    etf_df = api.fund_basic(
        market="E", status="L",
        fields="ts_code,name,benchmark,found_date",
    )
    etf_df["found_date"] = etf_df["found_date"].astype(str)
    etf_df = etf_df[etf_df["found_date"] < START_DATE].copy()
    logger.info("2024年前成立的ETF: %d 只", len(etf_df))

    codes = etf_df["ts_code"].tolist()

    logger.info("并发获取每只ETF成交额（%d并发）...", MAX_CONCURRENCY)
    s = time.time()
    amt_map = asyncio.run(get_etf_amounts_async(codes, trade_date))
    logger.info("获取 %d 只ETF成交额耗时: %.1f 秒", len(codes), time.time() - s)

    etf_df["amount"] = etf_df["ts_code"].map(amt_map)
    etf_df["benchmark"] = etf_df["benchmark"].fillna("未知")
    etf_active = etf_df[etf_df["amount"] > 0].copy()
    logger.info("有成交的ETF: %d 只", len(etf_active))

    selected = (
        etf_active
        .groupby("benchmark", group_keys=False)
        .apply(lambda g: g.loc[g["amount"].idxmax()])
        .reset_index(drop=True)
    )
    logger.info("按benchmark分组取最大成交额后: %d 只ETF", len(selected))
    return selected


def fetch_etf(code: str) -> bool:
    """下载单只ETF日K线"""
    api = get_api()
    try:
        df = rate_call(api.fund_daily, ts_code=code, start_date=START_DATE, end_date=END_DATE)
        if df is None or df.empty:
            return False
        df = df.rename(columns={"trade_date": "date", "vol": "volume"})
        df["date"] = df["date"].astype(str)
        df = df.sort_values("date").reset_index(drop=True)
        out_path = DATA_DIR / f"{code}.csv"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(out_path, index=False, encoding="utf-8")
        return True
    except Exception as e:
        logger.warning("下载 %s 失败: %s", code, e)
        return False


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    now = datetime.now()
    logger.info("=" * 60)
    logger.info("ETF数据下载任务")
    logger.info("当前时间: %s", now.strftime("%Y-%m-%d %H:%M"))
    logger.info("数据区间: %s ~ %s", START_DATE, END_DATE)
    logger.info("存储目录: %s", DATA_DIR)
    logger.info("策略: 同benchmark只保留成交额最大那只")
    logger.info("=" * 60)

    trade_date = get_trade_date()
    logger.info("最新交易日: %s", trade_date)

    selected_df = get_etf_list_with_amount(trade_date)
    codes = selected_df["ts_code"].tolist()
    logger.info("开始下载 %d 只ETF日K线...", len(codes))

    success, fail, skip = 0, 0, 0
    for i, code in enumerate(codes):
        out_path = DATA_DIR / f"{code}.csv"
        if out_path.exists():
            skip += 1
            continue
        ok = fetch_etf(code)
        if ok:
            success += 1
        else:
            fail += 1
        if (i + 1) % 50 == 0:
            logger.info("进度: %d/%d  成功:%d  失败:%d  跳过:%d",
                       i + 1, len(codes), success, fail, skip)

    logger.info("=" * 60)
    logger.info("下载完成！")
    logger.info("  总候选ETF: %d 只", len(codes))
    logger.info("  成功: %d，失败: %d，跳过(已存在): %d", success, fail, skip)
    logger.info("  数据目录: %s", DATA_DIR)

    list_path = DATA_DIR / "etf_list.csv"
    selected_df.to_csv(list_path, index=False, encoding="utf-8")
    logger.info("  ETF列表已保存: %s", list_path)


if __name__ == "__main__":
    main()