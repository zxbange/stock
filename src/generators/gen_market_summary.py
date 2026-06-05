#!/usr/bin/env python3
"""
每日A股市场总结生成器
数据来源：Tushare（全取本地聚合，不逐行业调用API）
流程：
  1. 拉取全市场股票当日+历史20日日线数据（批量一次）
  2. 按行业聚合计算行业温度（20日均线）
  3. 计算全市场温度（涨跌比+Amplitude+趋势）
  4. 输出 market_summary.json 到 daily_result/today/
输出：daily_result/today/market_summary.json
"""
import sys, os, json, time as _time, re
from pathlib import Path
from datetime import datetime, timedelta
from multiprocessing import Pool, cpu_count
import pandas as pd

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / 'src'))
from utils.log_config import get_logger
logger = get_logger("市场总结")

import tushare as ts
pro = ts.pro_api()

DATA_DIR   = PROJECT_ROOT / 'data'
TODAY_DIR  = PROJECT_ROOT / 'daily_result' / 'today'
OUT_JSON   = TODAY_DIR / 'market_summary.json'
TODAY      = None  # 动态计算，见 main()
# YESTERDAY = get_trade_dates(2)[-2]
START_20D  = (datetime.now() - timedelta(days=40)).strftime('%Y%m%d')  # 40天够取20个交易日

TODAY_DIR.mkdir(parents=True, exist_ok=True)

# ─── 工具函数 ───────────────────────────────────────────────────────────────

def _rate_limit():
    """内置速率限制：确保总速率 ≤ 500次/分钟"""
    _rate_limit._count = getattr(_rate_limit, '_count', 0) + 1
    if _rate_limit._count % 500 == 0:
        _time.sleep(60)
    elif _rate_limit._count % 50 == 0:
        _time.sleep(0.5)

def get_trade_dates(n=25):
    """获取最近n个交易日"""
    end = datetime.now().strftime('%Y%m%d')
    start = (datetime.now() - timedelta(days=60)).strftime('%Y%m%d')
    df = pro.trade_cal(start_date=start, end_date=end, fields='cal_date,is_open')
    df = df[df['is_open'] == 1]
    dates = sorted(df['cal_date'].tolist())
    return dates[-n:]

# ─── Step 1: 拉取全市场当日日线 ───────────────────────────────────────────

def fetch_market_breadth(trade_date):
    """获取全市场涨跌统计"""
    _rate_limit()
    try:
        df = pro.daily(trade_date=trade_date,
                       fields='ts_code,close,pct_chg,amount')
    except Exception as e:
        logger.warning("获取 %s 市场数据失败: %s", trade_date, e)
        return None

    if df.empty or 'pct_chg' not in df.columns:
        return None

    total = len(df)
    up    = int((df['pct_chg'] > 0).sum())
    dn    = int((df['pct_chg'] < 0).sum())
    flat  = total - up - dn
    avg_amp = float(df['pct_chg'].abs().mean())
    total_amount = float(df['amount'].sum())

    return {
        'date': trade_date,
        'total': total,
        'up': up, 'down': dn, 'flat': flat,
        'avg_amplitude': round(avg_amp, 2),
        'total_amount': int(total_amount),
    }


# ─── Step 2: 拉取主要指数数据 ───────────────────────────────────────────────

INDEX_CODES = {
    '000300.SH': '沪深300',
    '000001.SH': '上证指数',
    '399001.SZ': '深证成指',
    '399006.SZ': '创业板指',
    '000688.SH': '科创50',
    '000016.SH': '上证50',
}

def fetch_indices(trade_date):
    """获取主要指数收盘涨跌"""
    result = {}
    for code in INDEX_CODES:
        _rate_limit()
        try:
            df = pro.index_daily(ts_code=code, start_date=trade_date,
                                 end_date=trade_date,
                                 fields='ts_code,close,pre_close,pct_chg')
        except Exception as e:
            logger.warning("获取指数 %s 失败: %s", code, e)
            continue

        if df.empty:
            result[code] = {'name': INDEX_CODES[code], 'close': None,
                            'pct_chg': None}
        else:
            row = df.iloc[0]
            result[code] = {
                'name':    INDEX_CODES[code],
                'close':   round(float(row['close']), 2),
                'pct_chg': round(float(row['pct_chg']), 2),
            }
    return result


# ─── Step 3: 行业温度计算（批量聚合，不逐行业调用API） ────────────────────

def load_stock_industry():
    """从本地CSV加载股票行业映射（有缓存则直接用）"""
    cache = DATA_DIR / 'stock_industry.json'
    if cache.exists():
        mtime = cache.stat().st_mtime
        age = _time.time() - mtime
        if age < 86400:  # 24h内有效
            with open(cache, encoding='utf-8') as f:
                return json.load(f)

    logger.info("加载股票行业映射...")
    all_stocks = []
    for ex in ['SSE', 'SZSE', 'BSE']:
        _rate_limit()
        try:
            df = pro.stock_basic(exchange=ex, list_status='L',
                                 fields='ts_code,industry')
            if df is not None and not df.empty:
                all_stocks.append(df)
        except Exception as e:
            logger.warning("获取 %s 股票列表失败: %s", ex, e)

    if not all_stocks:
        return {}

    stocks_df = pd.concat(all_stocks, ignore_index=True)
    mapping = dict(zip(stocks_df['ts_code'], stocks_df['industry']))
    # 缓存
    with open(cache, 'w', encoding='utf-8') as f:
        json.dump(mapping, f)
    logger.info("行业映射加载完成: %d 只股票", len(mapping))
    return mapping


def fetch_industry_temps(trade_date):
    """批量聚合计算各行业今日温度，返回 {行业名: pct_chg}"""
    _rate_limit()
    try:
        df = pro.daily(trade_date=trade_date,
                       fields='ts_code,close,pct_chg')
    except Exception as e:
        logger.warning("获取 %s 行业温度数据失败: %s", trade_date, e)
        return {}

    if df.empty:
        return {}

    industry_map = load_stock_industry()
    if not industry_map:
        return {}

    df['industry'] = df['ts_code'].map(industry_map)
    df = df[df['industry'].notna() & (df['industry'] != '')]

    # 按行业聚合
    grouped = df.groupby('industry')['pct_chg'].agg(['mean', 'count'])
    grouped.columns = ['avg_return', 'stock_count']

    # 只保留至少有5只股票的行业
    grouped = grouped[grouped['stock_count'] >= 5]

    result = {}
    for ind, row in grouped.iterrows():
        result[ind] = round(float(row['avg_return']), 2)

    return result


def compute_industry_temperature_20d(industry_map, trade_dates):
    """计算各行业20日温度（每个行业取20日均值）"""
    # 拉批量日线：一次拉所有股票最近20日的日线（分批）
    all_data = []  # [(ts_code, trade_date, pct_chg)]

    # 用 daily_batch 风格：ts_code 留空查全市场
    for td in trade_dates:
        _rate_limit()
        try:
            df = pro.daily(trade_date=td, fields='ts_code,trade_date,pct_chg')
            if df is not None and not df.empty:
                all_data.append(df[['ts_code', 'trade_date', 'pct_chg']])
        except Exception as e:
            logger.warning("拉取 %s 日线失败: %s", td, e)

    if not all_data:
        return {}

    market_df = pd.concat(all_data, ignore_index=True)
    market_df['industry'] = market_df['ts_code'].map(industry_map)
    market_df = market_df[market_df['industry'].notna()]

    # 计算每个行业每个交易日的等权平均涨跌幅
    daily_industry = market_df.groupby(['trade_date', 'industry'])['pct_chg'].mean().reset_index()
    daily_industry.columns = ['trade_date', 'industry', 'ind_return']

    # 20日累积收益
    last_20d = daily_industry[daily_industry['trade_date'].isin(trade_dates[-20:])]
    industry_20d = last_20d.groupby('industry')['ind_return'].mean()

    # 归一化到 0-100（以0为中性，±3%对应50±50）
    temps = {}
    all_returns = industry_20d.values
    overall_mean = float(pd.Series(all_returns).mean()) if len(all_returns) > 0 else 0
    overall_std  = float(pd.Series(all_returns).std()) if len(all_returns) > 0 else 1
    if overall_std < 0.01:
        overall_std = 1.0

    for ind, ret in industry_20d.items():
        z = (ret - overall_mean) / overall_std
        temp = 50 + z * 15  # 偏离1个std → ±15度
        temp = max(0, min(100, round(temp, 1)))
        temps[ind] = temp

    return temps


# ─── Step 4: 计算全市场温度 ──────────────────────────────────────────────

def compute_market_temperature(breadth_series):
    """根据历史 breadth 计算市场温度 (0-100)"""
    if len(breadth_series) < 5:
        return 50.0

    recent = breadth_series[-14:]  # 最近14天
    ad_ratios = []
    amps = []

    for b in recent:
        total = b['total'] if b['total'] > 0 else 1
        ad_ratio = b['up'] / total
        amp = min(b['avg_amplitude'], 5) / 5  # 归一化振幅 (上限5%)
        ad_ratios.append(ad_ratio)
        amps.append(amp)

    avg_ad = sum(ad_ratios) / len(ad_ratios)
    avg_amp = sum(amps) / len(amps)

    # 5日趋势：温度变化方向
    if len(breadth_series) >= 5:
        early = breadth_series[-5:]
        late  = breadth_series[-1:]
        early_avg = sum(b['up'] / max(b['total'], 1) for b in early) / len(early)
        late_avg  = sum(b['up'] / max(b['total'], 1) for b in late) / max(len(late), 1)
        trend = max(-1, min(1, (late_avg - early_avg) * 2))
    else:
        trend = 0

    # 综合公式
    temp = 20 + avg_ad * 40 + avg_amp * 30 + trend * 10
    temp = max(0, min(100, round(temp, 1)))
    return temp


# ─── Step 5: 行业趋势（前5/后5） ─────────────────────────────────────────

def top_bottom_industries(industry_temps, top_n=5):
    sorted_inds = sorted(industry_temps.items(), key=lambda x: x[1], reverse=True)
    hot = sorted_inds[:top_n]
    cold = sorted_inds[-top_n:]
    return hot, list(reversed(cold))


# ─── 主函数 ────────────────────────────────────────────────────────────────

def generate(trade_date):
    """生成单日市场总结 JSON"""
    logger.info("=== 生成市场总结: %s ===", trade_date)

    # 1. 拉取主要指数
    indices_data = fetch_indices(trade_date)

    # 2. 全市场涨跌统计（今日 + 历史14天）
    trade_dates = get_trade_dates(20)
    breadth_today = fetch_market_breadth(trade_date)
    if breadth_today is None:
        logger.error("无法获取 %s 市场数据", trade_date)
        return None

    breadth_history = [breadth_today]
    for td in reversed(trade_dates[:-1]):
        b = fetch_market_breadth(td)
        if b:
            breadth_history.append(b)
        if len(breadth_history) >= 15:
            break

    # 3. 行业今日涨跌
    industry_today = fetch_industry_temps(trade_date)

    # 4. 行业20日温度（每周更新一次，日常跳过）
    cache_20d = DATA_DIR / 'industry_temp_20d.json'
    need_update = True
    if cache_20d.exists():
        age = _time.time() - cache_20d.stat().st_mtime
        if age < 86400 * 3:  # 3天内更新过
            with open(cache_20d, encoding='utf-8') as f:
                industry_20d_temps = json.load(f)
            need_update = False
            logger.info("复用行业温度缓存 (age=%.1fh)", age/3600)

    if need_update:
        logger.info("计算行业20日温度（需拉数据，请稍候）...")
        industry_map = load_stock_industry()
        industry_20d_temps = compute_industry_temperature_20d(industry_map, trade_dates)
        with open(cache_20d, 'w', encoding='utf-8') as f:
            json.dump(industry_20d_temps, f)
        logger.info("行业20日温度计算完成: %d 个行业", len(industry_20d_temps))

    # 合并今日涨跌到行业温度排序
    final_industry_temps = {}
    for ind, today_ret in industry_today.items():
        temp_20d = industry_20d_temps.get(ind, 50)
        # 今日涨跌调整温度（今日涨跌占40%权重）
        today_adj = max(-20, min(20, today_ret * 5))
        final_industry_temps[ind] = round(temp_20d + today_adj * 0.4, 1)

    # 5. 全市场温度
    market_temp = compute_market_temperature(breadth_history)

    # 6. 趋势
    hot_inds, cold_inds = top_bottom_industries(final_industry_temps, 5)

    # 7. 市场风格（大小盘：用沪深300 vs 创业板相对强弱做代理）
    hs300_chg  = indices_data.get('000300.SH', {}).get('pct_chg')
    cyb_chg    = indices_data.get('399006.SZ', {}).get('pct_chg')
    style_bias = '均衡'
    if hs300_chg is not None and cyb_chg is not None:
        diff = hs300_chg - cyb_chg
        style_bias = '大盘占优' if diff > 0.5 else ('小盘偏强' if diff < -0.5 else '均衡')

    # 8. 组装结果
    result = {
        'date':           trade_date,
        'indices':        indices_data,
        'market': {
            'temperature':   market_temp,
            'total_stocks':  breadth_today['total'],
            'up':            breadth_today['up'],
            'down':          breadth_today['down'],
            'flat':          breadth_today['flat'],
            'avg_amplitude': breadth_today['avg_amplitude'],
            'total_amount':  breadth_today['total_amount'],
        },
        'industry_temps': final_industry_temps,
        'hot_industries': hot_inds,
        'cold_industries': cold_inds,
        'style_bias':     style_bias,
        'hs300_chg':      hs300_chg,
        'cyb_chg':       cyb_chg,
    }

    return result


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='每日A股市场总结')
    parser.add_argument('--date', default=None, help='指定日期 YYYYMMDD，默认今天')
    parser.add_argument('--mode', choices=['full', 'quick'], default='quick',
                        help='full=含行业20日温度(慢), quick=只拉今日数据(默认)')
    args = parser.parse_args()

    trade_dates = get_trade_dates(5)
    _DEFAULT_DATE = trade_dates[-1]  # 最近一个交易日
    target = args.date or _DEFAULT_DATE

    if args.mode == 'full':
        # 清除缓存强制全量
        cache = DATA_DIR / 'industry_temp_20d.json'
        if cache.exists():
            cache.unlink()

    result = generate(target)
    if result:
        with open(OUT_JSON, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        logger.info("市场总结已写入: %s", OUT_JSON)
        logger.info("市场温度: %.1f°  涨跌: %d/%d/%d  成交额: %.0f亿",
                    result['market']['temperature'],
                    result['market']['up'],
                    result['market']['down'],
                    result['market']['flat'],
                    result['market']['total_amount'] / 1e5)
    else:
        logger.error("生成失败")