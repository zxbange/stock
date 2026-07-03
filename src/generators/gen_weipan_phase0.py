#!/usr/bin/env python3
"""
微盘温度计 Phase0: 下载所有原始数据到本地（按日调用Tushare API）
两阶段架构：先下载再计算，失败可断点续传
采样频率：每隔5个交易日（与JQ一致）
"""
import os, sys, tushare as ts, pandas as pd, numpy as np, threading, time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.log_config import get_logger

logger = get_logger('微盘下载')

PRO = ts.pro_api()
DATA_DIR = Path('/home/bange/stock/data/weipan_raw')
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Rate limiting: 500次/分钟
_RATE_HIST, _RATE_LOCK = [], threading.Lock()

def rate_limit():
    with _RATE_LOCK:
        now = time.time()
        _RATE_HIST[:] = [t for t in _RATE_HIST if now - t < 60]
        if len(_RATE_HIST) >= 500:
            st = 60 - (now - _RATE_HIST[0]) + 0.1
            if st > 0: time.sleep(st)
            _RATE_HIST[:] = [t for t in _RATE_HIST if time.time() - t < 60]
        _RATE_HIST.append(time.time())

# ─── Step0: 股票列表 ────────────────────────────────────────────────────

def download_stock_list():
    path = DATA_DIR / 'stock_list.csv'
    if path.exists() and path.stat().st_size > 1000:
        logger.info("股票列表已存在，跳过")
        return
    logger.info("Step 0: 下载股票列表...")
    rate_limit()
    df = PRO.stock_basic(list_status='L', fields='ts_code,name,list_date,is_st')
    df.to_csv(path, index=False, encoding='utf-8')
    logger.info("股票列表: %d 只", len(df))

# ─── Step 1: daily_basic（按日调用，获取全部交易日）─────────────────

def download_daily_basic():
    path = DATA_DIR / 'daily_basic.csv'
    
    # 获取所有交易日
    rate_limit()
    cal = PRO.trade_cal(start_date='20171201', end_date='20260605', fields='cal_date,is_open')
    all_days = sorted(cal[cal['is_open'] == 1]['cal_date'].tolist())
    logger.info("全部交易日: %d 个", len(all_days))
    
    # 每隔5个交易日采样一次（与JQ一致）
    sample_days = all_days[::5]
    logger.info("采样间隔5个交易日: %d 个日期", len(sample_days))
    
    # 检查已下载的日期
    existing_dates = set()
    if path.exists() and path.stat().st_size > 1000:
        try:
            ex = pd.read_csv(path, dtype={'trade_date': str})
            existing_dates = set(ex['trade_date'].unique())
            logger.info("已有 %d 个日期", len(existing_dates))
        except:
            existing_dates = set()
    
    missing = [d for d in sample_days if d not in existing_dates]
    logger.info("缺失 %d 个日期", len(missing))
    
    if not missing:
        logger.info("daily_basic 已完整，跳过")
        return
    
    first = not path.exists()
    total = len(missing)
    done = 0
    fail = 0
    
    logger.info("开始下载 daily_basic (%d 个日期)...", total)
    for date in missing:
        rate_limit()
        try:
            df = PRO.daily_basic(
                trade_date=date,
                fields='ts_code,trade_date,turnover_rate,pe,pb,total_mv,circulating_mv'
            )
            if df is not None and not df.empty:
                df['trade_date'] = df['trade_date'].astype(str)
                df.to_csv(path, index=False, encoding='utf-8', mode='a' if not first else 'w',
                          header=first)
                first = False
                done += 1
            else:
                fail += 1
        except Exception as e:
            fail += 1
            logger.warning("  daily_basic %s 失败: %s", date, e)
        
        if (done + fail) % 50 == 0 or (done + fail) == total:
            logger.info("进度: %d/%d (失败%d)", done + fail, total, fail)
    
    logger.info("daily_basic 完成: 成功%d 失败%d", done, fail)

# ─── Step 2: daily amount（按日调用）───────────────────────────────────

def download_daily_amount():
    path = DATA_DIR / 'daily_amount.csv'
    
    # 获取所有交易日
    rate_limit()
    cal = PRO.trade_cal(start_date='20171201', end_date='20260605', fields='cal_date,is_open')
    all_days = sorted(cal[cal['is_open'] == 1]['cal_date'].tolist())
    sample_days = all_days[::5]  # 每隔5个交易日
    
    existing_dates = set()
    if path.exists() and path.stat().st_size > 1000:
        try:
            ex = pd.read_csv(path, dtype={'trade_date': str})
            existing_dates = set(ex['trade_date'].unique())
            logger.info("已有 %d 个日期", len(existing_dates))
        except:
            existing_dates = set()
    
    missing = [d for d in sample_days if d not in existing_dates]
    logger.info("缺失 %d 个日期", len(missing))
    
    if not missing:
        logger.info("daily_amount 已完整，跳过")
        return
    
    first = not path.exists()
    total = len(missing)
    done = 0
    fail = 0
    
    logger.info("开始下载 daily_amount (%d 个日期)...", total)
    for date in missing:
        rate_limit()
        try:
            df = PRO.daily(trade_date=date, fields='ts_code,trade_date,amount')
            if df is not None and not df.empty:
                df['trade_date'] = df['trade_date'].astype(str)
                df.to_csv(path, index=False, encoding='utf-8', mode='a' if not first else 'w',
                          header=first)
                first = False
                done += 1
            else:
                fail += 1
        except Exception as e:
            fail += 1
            logger.warning("  daily %s 失败: %s", date, e)
        
        if (done + fail) % 50 == 0 or (done + fail) == total:
            logger.info("进度: %d/%d (失败%d)", done + fail, total, fail)
    
    logger.info("daily_amount 完成: 成功%d 失败%d", done, fail)

# ─── Step 3: 收盘价（按日调用）────────────────────────────────────────

def download_close_prices():
    path = DATA_DIR / 'close_prices.csv'
    
    # 获取所有交易日
    rate_limit()
    cal = PRO.trade_cal(start_date='20171201', end_date='20260605', fields='cal_date,is_open')
    all_days = sorted(cal[cal['is_open'] == 1]['cal_date'].tolist())
    sample_days = all_days[::5]  # 每隔5个交易日
    
    existing_dates = set()
    if path.exists() and path.stat().st_size > 1000:
        try:
            ex = pd.read_csv(path, dtype={'trade_date': str})
            existing_dates = set(ex['trade_date'].unique())
            logger.info("已有 %d 个日期", len(existing_dates))
        except:
            existing_dates = set()
    
    missing = [d for d in sample_days if d not in existing_dates]
    logger.info("缺失 %d 个日期", len(missing))
    
    if not missing:
        logger.info("close_prices 已完整，跳过")
        return
    
    first = not path.exists()
    total = len(missing)
    done = 0
    fail = 0
    
    logger.info("开始下载 close_prices (%d 个日期)...", total)
    for date in missing:
        rate_limit()
        try:
            df = PRO.daily(trade_date=date, fields='ts_code,trade_date,close')
            if df is not None and not df.empty:
                df['trade_date'] = df['trade_date'].astype(str)
                df.to_csv(path, index=False, encoding='utf-8', mode='a' if not first else 'w',
                          header=first)
                first = False
                done += 1
            else:
                fail += 1
        except Exception as e:
            fail += 1
            logger.warning("  close %s 失败: %s", date, e)
        
        if (done + fail) % 50 == 0 or (done + fail) == total:
            logger.info("进度: %d/%d (失败%d)", done + fail, total, fail)
    
    logger.info("close_prices 完成: 成功%d 失败%d", done, fail)

# ─── 主函数 ─────────────────────────────────────────────────────────────

def main():
    logger.info("=== 微盘 Phase0: 数据下载（按日调用） ===")
    t0 = time.time()
    download_stock_list()
    download_daily_basic()
    download_daily_amount()
    download_close_prices()
    logger.info("=== Phase0 完成，耗时 %.0f 秒 ===", time.time() - t0)

if __name__ == '__main__':
    main()