#!/usr/bin/python3
"""
从Tushare下载A股财务数据（年报+季报）
动态计算：年报2023/2024/2025 + 季报Q1/Q2/Q3 2023/2024/2025 + 当前年Q1
"""
import sys
import time
import threading
from pathlib import Path
from datetime import datetime

import pandas as pd
import tushare as ts
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.log_config import get_logger
logger = get_logger("下载财务数据")



PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data/financial"
CALL_INTERVAL = 60.0 / 195

_lock = threading.Lock()
_last_call = 0.0


def get_api():
    return ts.pro_api()


def rate_call(func, *args, **kwargs):
    global _last_call
    with _lock:
        now = time.time()
        wait = CALL_INTERVAL - (now - _last_call)
        if wait > 0:
            time.sleep(wait)
        _last_call = time.time()
    return func(*args, **kwargs)


def build_periods():
    """
    年报: 2023/2024/2025
    Q1:    2023/2024/2025Q1 + 当前年Q1（如果有）
    Q2:    2023/2024/2025Q2
    Q3:    2023/2024/2025Q3
    """
    now = datetime.now()
    year = now.year
    month = now.month

    # 年报
    annual = [f"{y}1231" for y in [year - 3, year - 2, year - 1]]

    # Q1：需要4条（2023/2024/2025Q1 + 当前年Q1）才能计算3组同比
    q1 = [f"{y}0331" for y in [year - 3, year - 2, year - 1]]
    if month >= 4:  # Q1数据一般4月出
        q1.append(f"{year}0331")

    # Q2、Q3：各3条
    q2 = [f"{y}0630" for y in [year - 3, year - 2, year - 1]]
    q3 = [f"{y}0930" for y in [year - 3, year - 2, year - 1]]

    all_periods = sorted(set(annual + q1 + q2 + q3))
    return annual, q1, q2, q3, all_periods


def get_all_codes() -> list:
    api = get_api()
    df = api.stock_basic(list_status='L', fields='ts_code')
    return df['ts_code'].tolist()


def fetch_stock(code: str, api, all_periods: list) -> bool:
    all_data = []
    for period in all_periods:
        try:
            df = rate_call(
                api.income,
                ts_code=code,
                period=period,
                fields='ts_code,ann_date,period,end_date,n_income,basic_eps'
            )
            if df is not None and not df.empty:
                df = df.drop_duplicates(subset=['end_date'], keep='first')
                all_data.append(df)
        except Exception:
            pass

    if not all_data:
        return False

    combined = pd.concat(all_data, ignore_index=True)
    combined['end_date'] = combined['end_date'].astype(str)
    combined = combined[combined['end_date'].str.len() == 8]

    result = combined[['ts_code', 'ann_date', 'end_date', 'n_income', 'basic_eps']]
    result = result.drop_duplicates(subset=['end_date'], keep='first')
    result = result.sort_values('end_date')

    if result.empty:
        return False

    result.to_csv(DATA_DIR / f"{code}.csv", index=False, encoding='utf-8')
    return True


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    annual, q1, q2, q3, all_periods = build_periods()
    now = datetime.now()
    logger.info("开始下载A股财务数据")
    logger.info("当前时间: %s", now.strftime("%Y-%m"))
    logger.info("年报: %s", annual)
    logger.info("Q1:  %s", q1)
    logger.info("Q2:  %s", q2)
    logger.info("Q3:  %s", q3)

    api = get_api()
    codes = get_all_codes()
    logger.info("共 %d 支A股", len(codes))

    success = 0
    fail = 0

    for i, code in tqdm(enumerate(codes), total=len(codes), desc="下载财务数据", leave=True):
        ok = fetch_stock(code, api, all_periods)
        if ok:
            success += 1
        else:
            fail += 1


    logger.info("下载完成！成功 %d 支，失败 %d 支", success, fail)


if __name__ == "__main__":
    main()
