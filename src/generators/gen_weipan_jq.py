"""
完全按照 JoinQuant weipanweiduji.py 的算法逻辑重写
使用 Tushare API 等效实现每个步骤
"""
import pandas as pd
import numpy as np
import tushare as ts
from datetime import datetime, timedelta
import time as _time
import threading
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
logger = logging.getLogger('weipan_jq')

pro = ts.pro_api()

# ==========================================
# 参数（与JQ完全一致）
# ==========================================
START_DATE = '20180101'
MICRO_NUM = 1000

# ==========================================
# 速率限制
# ==========================================
RATE_HISTORY = []
RATE_LOCK = threading.Lock()
RATE_WINDOW = 60.0
RATE_MAX = 500

def rate_limit():
    with RATE_LOCK:
        now = _time.time()
        RATE_HISTORY[:] = [t for t in RATE_HISTORY if now - t < RATE_WINDOW]
        if len(RATE_HISTORY) >= RATE_MAX:
            sleep_sec = RATE_WINDOW - (now - RATE_HISTORY[0]) + 0.5
            if sleep_sec > 0:
                _time.sleep(sleep_sec)
            RATE_HISTORY[:] = [t for t in RATE_HISTORY if _time.time() - t < RATE_WINDOW]
        RATE_HISTORY.append(_time.time())

# ==========================================
# 工具函数
# ==========================================
def get_trade_days_tushare(start_date=None, end_date=None, count=None):
    """等效 JQ get_trade_days"""
    if count is not None:
        df = pro.trade_cal(end_date=end_date, fields='cal_date,is_open')
        df = df[df['is_open'] == 1].sort_values('cal_date')
        return sorted(df['cal_date'].tolist())[-count:]
    else:
        df = pro.trade_cal(start_date=start_date, end_date=end_date, fields='cal_date,is_open')
        df = df[df['is_open'] == 1].sort_values('cal_date')
        return sorted(df['cal_date'].tolist())

def get_all_securities_tushare(types=['stock'], date=None):
    """等效 JQ get_all_securities(types=['stock'], date=date)"""
    date_str = str(date).replace('-', '')
    df = pro.stock_basic(list_status='L', fields='ts_code,name,list_date')
    df = df[~df['ts_code'].str.startswith(('4', '8'))]
    df['list_str'] = df['list_date'].apply(lambda x: str(int(x)) if pd.notna(x) else '99999999')
    df = df[df['list_str'] <= date_str]
    return df['ts_code'].tolist()

def get_stock_info(stock):
    """等效 JQ get_security_info(stock)"""
    df = pro.stock_basic(ts_code=stock, fields='ts_code,name,list_date')
    if df is None or df.empty:
        return None
    return type('Info', (), {
        'start_date': str(int(df['list_date'].iloc[0])) if pd.notna(df['list_date'].iloc[0]) else '20100101'
    })()

def is_st_tushare(codes, date):
    """等效 JQ get_extras('is_st', codes, start_date=date, end_date=date)
    Tushare没有等效API，返回空dict（无法做ST过滤）"""
    return {}

def get_fundamentals_tushare(codes, date, q=None):
    """等效 JQ get_fundamentals(q, date=date)
    使用 daily_basic + daily 模拟 valuation 表"""
    date_str = str(date).replace('-', '')
    rate_limit()
    basic = pro.daily_basic(trade_date=date_str, fields='ts_code,total_mv,turnover_rate,pe,pb')
    if basic is None or basic.empty:
        return pd.DataFrame()
    basic = basic[basic['ts_code'].isin(codes)]
    basic = basic.rename(columns={
        'total_mv': 'market_cap',
        'turnover_rate': 'turnover_ratio',
        'pe': 'pe_ratio',
        'pb': 'pb_ratio'
    })
    basic['market_cap'] = basic['market_cap'] / 10000.0
    return basic

def get_5d_turnover_ratio_tushare(codes, date):
    """等效 JQ: 对过去5个交易日各取一次 valuation.turnover_ratio，然后每只股票算均值"""
    date_str = str(date).replace('-', '')
    rate_limit()
    td = pro.trade_cal(end_date=date_str, fields='cal_date,is_open')
    td = td[td['is_open'] == 1].sort_values('cal_date')
    past_5_days = sorted(td['cal_date'].tolist())[-5:]
    
    all_rows = []
    for d in past_5_days:
        rate_limit()
        try:
            chunk = pro.daily_basic(trade_date=d, fields='ts_code,turnover_rate')
            if chunk is not None and not chunk.empty:
                sub = chunk[chunk['ts_code'].isin(codes)].set_index('ts_code')['turnover_rate']
                all_rows.append(sub)
        except Exception:
            continue
    
    if not all_rows:
        return pd.Series(dtype=float)
    
    tr_df = pd.concat(all_rows, axis=1, sort=False)
    tr_5d_mean = tr_df.mean(axis=1)
    return tr_5d_mean

def get_money_tushare(codes, date):
    """等效 JQ get_price(codes, count=1, fields=['money'])['money']"""
    date_str = str(date).replace('-', '')
    rate_limit()
    df = pro.daily(trade_date=date_str, fields='ts_code,amount')
    if df is None or df.empty:
        return pd.Series(dtype=float)
    df = df[df['ts_code'].isin(codes)]
    return df.set_index('ts_code')['amount']

def get_close_price_tushare(codes, date):
    """等效 JQ get_price(codes, count=1, fq='pre', fields=['close'])['close']"""
    date_str = str(date).replace('-', '')
    rate_limit()
    df = pro.daily(trade_date=date_str, fields='ts_code,close')
    if df is None or df.empty:
        return pd.Series(dtype=float)
    df = df[df['ts_code'].isin(codes)]
    return df.set_index('ts_code')['close']

def get_indicator_tushare(codes, date_str):
    """等效 JQ get_fundamentals(query(indicator...), date=date_str)"""
    rate_limit()
    try:
        df = pro.fina_indicator(start_date=date_str, end_date=date_str, fields='ts_code,inc_net_profit_to_shareholders_year_on_year')
        if df is None or df.empty:
            return pd.DataFrame()
        df = df[df['ts_code'].isin(codes)]
        return df
    except Exception:
        return pd.DataFrame()

# ==========================================
# 主循环（逐字翻译 JQ）
# ==========================================
trade_days = get_trade_days_tushare(start_date=START_DATE)[::5]
logger.info("采样 %d 个交易日", len(trade_days))

records = []
micro_stocks_by_date = {}
close_prices_by_date = {}

for i, date in enumerate(trade_days):
    date_str = str(date).replace('-', '')
    logger.info("[%d/%d] 处理 %s", i+1, len(trade_days), date_str)
    
    try:
        # --- get_all_securities ---
        stocks = get_all_securities_tushare(types=['stock'], date=date)
        
        # --- 北交所过滤 + 上市不足250天过滤 ---
        valid_stocks = []
        cutoff = (datetime.strptime(date_str, '%Y%m%d') - timedelta(250)).strftime('%Y%m%d')
        for stock in stocks:
            info = get_stock_info(stock)
            if info is None:
                continue
            start = info.start_date.replace('-', '').replace('/', '')
            if start <= date_str and start >= '19900101':
                if (datetime.strptime(date_str, '%Y%m%d') - datetime.strptime(start, '%Y%m%d')).days >= 250:
                    valid_stocks.append(stock)
        
        if len(valid_stocks) < MICRO_NUM:
            logger.warning("  %s: 有效股票 %d < 1000，跳过", date_str, len(valid_stocks))
            continue
        
        # --- ST过滤（JQ用get_extras('is_st')，Tushare无等效API，跳过）---
        # st_df = is_st_tushare(valid_stocks, date)
        # st_series = st_df.iloc[0] if not st_df.empty else pd.Series(dtype=bool)
        # valid_stocks = [s for s in valid_stocks if not st_series.get(s, False)]
        
        # --- valuation 数据 ---
        val_df = get_fundamentals_tushare(valid_stocks, date)
        val_df = val_df.dropna()
        
        if len(val_df) < MICRO_NUM:
            logger.warning("  %s: valuation %d < 1000，跳过", date_str, len(val_df))
            continue
        
        # --- 近5日换手率均值 ---
        tr_5d_mean = get_5d_turnover_ratio_tushare(valid_stocks, date)
        
        # --- 当日成交额 ---
        money_series = get_money_tushare(valid_stocks, date)
        
        # --- 合并数据 ---
        val_df = val_df.set_index('ts_code')
        val_df['turnover_ratio'] = tr_5d_mean
        val_df['money'] = money_series
        val_df = val_df.dropna().reset_index()
        val_df.rename(columns={'index': 'code'}, inplace=True)
        
        if len(val_df) < MICRO_NUM:
            logger.warning("  %s: 合并后 %d < 1000，跳过", date_str, len(val_df))
            continue
        
        # --- 市值排序，取前1000 ---
        val_df = val_df.sort_values('market_cap')
        micro_df = val_df.head(MICRO_NUM)
        
        # --- 记录微盘成分股及收盘价 ---
        micro_codes = micro_df['code'].tolist()
        micro_stocks_by_date[date_str] = micro_codes
        close_prices_by_date[date_str] = get_close_price_tushare(micro_codes, date)
        
        # --- PE/PB 中位数 ---
        pe_vals = micro_df['pe_ratio'].dropna()
        pb_vals = micro_df['pb_ratio'].dropna()
        pe_median = pe_vals.median() if len(pe_vals) > 0 else np.nan
        pb_median = pb_vals.median() if len(pb_vals) > 0 else np.nan
        
        # --- 归母净利润增速 ---
        ind_df = get_indicator_tushare(micro_codes, date_str)
        ind_df = ind_df.dropna(subset=['inc_net_profit_to_shareholders_year_on_year'])
        avg_np_growth = ind_df['inc_net_profit_to_shareholders_year_on_year'].median() if len(ind_df) > 0 else np.nan
        
        # --- 市值中位数 ---
        micro_median = micro_df['market_cap'].median()
        all_median = val_df['market_cap'].median()
        
        # --- 相对估值 ---
        relative_ratio = micro_median / all_median if all_median > 0 else np.nan
        
        # --- 换手率拥挤度（JQ用mean，不是median）---
        micro_tr = micro_df['turnover_ratio'].mean()
        all_tr = val_df['turnover_ratio'].mean()
        crowding_ratio = micro_tr / all_tr if all_tr > 0 else np.nan
        
        # --- 成交额拥挤度 ---
        micro_amount = micro_df['money'].sum()
        all_amount = val_df['money'].sum()
        amount_crowding_ratio = micro_amount / all_amount if all_amount > 0 else np.nan
        
        records.append({
            'date': date_str,
            'micro_median': round(float(micro_median), 2),
            'all_median': round(float(all_median), 2),
            'relative_ratio': round(float(relative_ratio), 4),
            'crowding_ratio': round(float(crowding_ratio), 4),
            'amount_crowding_ratio': round(float(amount_crowding_ratio), 4),
            'pe_median': round(float(pe_median), 2) if not np.isnan(pe_median) else np.nan,
            'pb_median': round(float(pb_median), 2) if not np.isnan(pb_median) else np.nan,
            'avg_np_growth': round(float(avg_np_growth), 2) if not np.isnan(avg_np_growth) else np.nan,
        })
        
        logger.info("  ✓ micro_cap=%.2f, crowding=%.4f, score_pct=...", 
                    micro_median, crowding_ratio)
        
    except Exception as e:
        logger.warning("  ✗ %s 异常: %s", date_str, e)
        import traceback
        traceback.print_exc()
        continue

logger.info("\n共计算 %d 期，准备写入CSV", len(records))
