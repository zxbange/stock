import sys
import logging
import warnings
import datetime as dt

import tushare as ts
import time
import argparse
from threading import Lock
import pandas as pd
from typing import List, Optional
from pathlib import Path
PROJECT_ROOT = Path(__file__).parent.parent.parent
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm
import random

# ========= 配置日志（统一标准格式）=========
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.log_config import get_logger
logger = get_logger("下载数据")

warnings.filterwarnings("ignore")

# 屏蔽第三方库多余 INFO 日志
for noisy in ("httpx", "urllib3", "_client", "akshare"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

# ======== 获取股票列表 ==========
def get_stock_list() -> pd.DataFrame:
    data = pro.query("stock_basic", fields='ts_code')
    return data

# ============= 数据校验 ===========

def validate(df: pd.DataFrame) -> pd.DataFrame:
    df = df.drop_duplicates(subset="date").sort_values("date").reset_index(drop=True)
    if df["date"].isna().any():
        raise ValueError("存在缺失日期！")
    if (df["date"] > pd.Timestamp.today()).any():
        raise ValueError("数据包含未来日期，可能抓取错误！")
    return df

def drop_dup_columns(df: pd.DataFrame) -> pd.DataFrame:
    return df.loc[:, ~df.columns.duplicated()]

# ======= 获取单个股票日线数据 =========
def get_kline(code, start, end):
    adj = 'qfq' # 默认获取前复权价格
    freq = 'D'  # 默认获取天级别K线
    for attempt in range (1,4):
        try:
            df = ts.pro_bar(
                ts_code = code,
                adj = adj,
                start_date = start,
                end_date = end,
                freq = freq,
            )
            break
        except Exception as e:
            logger.warning("Tushare 拉去 %s 失败（%d/3): %s", code, attempt, e)
            time.sleep(random.uniform(1,2) * attempt)
    else:
        return pd.DataFrame()

    if df is None or df.empty:
        return pd.DataFrame()
    
    df = df.rename(columns={"trade_date": "date", "vol": "volume"}).copy()
    df["date"] = pd.to_datetime(df["date"])
    df[[c for c in df.columns if c != "date"]] = df[[c for c in df.columns if c!= "date"]].apply(
        pd.to_numeric, errors="coerce"
    )
    return df.sort_values("date").reset_index(drop=True)

def get_one(code:str, start:str, end:str, out_dir:Path):
    csv_path = out_dir / f"{code}.csv"
    if csv_path.exists():
        try:
            existing = pd.read_csv(csv_path, parse_dates=["date"])
            last_date = existing["date"].max()
            if last_date.date() > pd.to_datetime(end, format="%Y%m%d").date():
                logger.debug("%s 已经是最新, 无需更新", code)
                return
            start = last_date.strftime("%Y%m%d")
        except Exception:
            logger.exception("读取 %s 失败, 将重新下载", csv_path)
    
    for attempt in range (1, 4):
        try:
            new_df = get_kline(code, start, end)
            if new_df.empty:
                logger.debug("%s 无新数据", code)
                break
            new_df = validate(new_df)
            if csv_path.exists():
                old_df = pd.read_csv(
                    csv_path,
                    parse_dates=["date"],
                    index_col=False
                )
                old_df = drop_dup_columns(old_df)
                new_df = drop_dup_columns(new_df)
                new_df = (
                    pd.concat([old_df, new_df], ignore_index=True)
                    .drop_duplicates(subset="date")
                    .sort_values("date")
                )
            new_df.to_csv(csv_path, index=False)
            break
        except Exception:
            logger.exception("%s 第 %d 次抓取失败", code, attempt)
            time.sleep(random.uniform(1, 3) * attempt)  # 指数退避
    else:
        logger.error("%s 三次抓取均失败，已跳过！", code)


def main():
    # exit(0)
    parser = argparse.ArgumentParser(description="抓取股票K线")
    parser.add_argument("--start", default="20240101", help="起始日期 YYYYMMDD 或 'today'")
    parser.add_argument("--end", default="today", help="结束日期 YYYYMMDD 或 'today'")
    parser.add_argument("--out", default=str(BASE / "data/kline"), help="股票信息文件输出路径")
    parser.add_argument("--workers", type=int, default=8, help="并发抓取工作线程数")
    args = parser.parse_args()

    start = dt.datetime.today().strftime("%Y%m%d") if args.start.lower() == "today" else args.start
    end = dt.datetime.today().strftime("%Y%m%d") if args.end.lower () == "today" else args.end

    # ========== 填写Tushare信息 ==========
    ts_token = "34ffa547652d6ddcc3b8ace33adb97f6f582656a02599a059091c705"
    global pro 
    ts.set_token(ts_token)
    pro= ts.pro_api()

    # ========== 创建输出目录 ==========
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    # ========== 获取股票列表 ==========
    data  = get_stock_list()
    codes = data['ts_code'].str.zfill(6).tolist()

    # ========== 读取本地股票池并合并 =========
    local_codes = [p.stem for p in out_dir.glob("*.csv")]
    codes = sorted(set(codes) | set(local_codes))

    if not codes:
        logger.error("筛选结果为空，")
        sys.exit(1)
    
    logger.info(
        "开始抓取 %d 支股票 | 日期: %s → %s",
        len(codes),
        start,
        end,
    )

    # ============ 多线程抓取 =============
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [
            executor.submit(
            get_one,
            code,
            start,
            end,
            out_dir,
            )
            for code in codes
        ]
        # 速率限制：500次/分钟 = 8.33次/秒，每次间隔约0.12秒
        last_req = [0.0]
        _lock = Lock()
        MIN_INTERVAL = 1.0 / 8.33

        def rate_limit():
            with _lock:
                now = time.time()
                wait = MIN_INTERVAL - (now - last_req[0])
                if last_req[0] > 0 and wait > 0:
                    time.sleep(wait)
                last_req[0] = time.time()

        for _ in tqdm(as_completed(futures), total=len(codes), desc="下载进度"):
            rate_limit()
    logger.info("全部任务完成, 数据已保存至 %s", out_dir.resolve())

if __name__ == "__main__":
    main()
