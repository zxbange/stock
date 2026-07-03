#!/usr/bin/env python3
"""
微盘温度计 Phase1: 从本地CSV计算所有交易日指标
两阶段架构：Phase0下载原始数据 → Phase1本地计算 → Phase2等权指数 → Phase3写CSV+图表
"""
import os, sys, pandas as pd, numpy as np, time
from pathlib import Path
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.log_config import get_logger

logger = get_logger('微盘计算')

RAW_DIR = Path('/home/bange/stock/data/weipan_raw')
OUTPUT_DIR = Path('/home/bange/stock/data')
WEIPAN_IMG_DIR = Path('/home/bange/stock/data/weipan_imgs')

WORKERS = 1  # 串行以支持 prev_micro_codes 前向填充

# ─── 加载原始数据 ─────────────────────────────────────────────────────────

def load_raw_data():
    """加载原始数据并预索引（按日期分组）"""
    logger.info("加载原始数据...")
    t0 = time.time()

    stock_list = pd.read_csv(RAW_DIR / 'stock_list.csv', dtype={'ts_code': str})
    stock_list['list_date'] = stock_list['list_date'].astype(str)
    logger.info(" 股票列表: %d 只", len(stock_list))

    basic = pd.read_csv(RAW_DIR / 'daily_basic.csv', dtype={'trade_date': str})
    logger.info("  daily_basic: %d 行", len(basic))

    amount = pd.read_csv(RAW_DIR / 'daily_amount.csv', dtype={'trade_date': str})
    logger.info("  daily_amount: %d 行", len(amount))

    close = pd.read_csv(RAW_DIR / 'close_prices.csv', dtype={'trade_date': str})
    logger.info("  close_prices: %d 行", len(close))

    # 预索引：按trade_date分组，O(1)查询替代每次全表扫描
    basic_idx = {str(d): g for d, g in basic.groupby('trade_date')}
    amount_idx = {str(d): g for d, g in amount.groupby('trade_date')}
    logger.info("  预索引完成: %d 个日期", len(basic_idx))
    
    # 前向填充：对每个日期，补充缺失股票的 market_cap 和 amount
    # 使用前一个有效日期的数据
    logger.info("  前向填充缺失数据...")
    all_dates_sorted = sorted(basic['trade_date'].unique())
    
    # 构建每只股票的market_cap历史（用于前向填充）
    # 从后往前，为每个日期补充缺失股票
    last_basic = None  # 上一个有效的basic_day DataFrame
    last_amount = None  # 上一个有效的amount_day DataFrame
    
    filled_basic_idx = {}
    filled_amount_idx = {}
    
    for date_str in all_dates_sorted:
        # 获取当日数据
        basic_day = basic_idx.get(date_str)
        amount_day = amount_idx.get(date_str)
        
        if basic_day is not None and len(basic_day) >= 50:
            # 数据充足（至少50只），直接使用
            last_basic = basic_day.copy()
            last_amount = amount_day.copy() if amount_day is not None else None
            filled_basic_idx[date_str] = basic_day
            if amount_day is not None:
                filled_amount_idx[date_str] = amount_day
            elif last_amount is not None:
                filled_amount_idx[date_str] = last_amount
        elif last_basic is not None:
            # 数据不足，用上次数据前向填充
            if basic_day is not None and len(basic_day) > 0:
                # 合并：当日数据 + 缺失股票用上次数据补充
                last_codes = set(last_basic['ts_code'])
                today_codes = set(basic_day['ts_code'])
                missing_codes = last_codes - today_codes
                
                if missing_codes and last_amount is not None:
                    # 补充缺失股票
                    missing_basic = last_basic[last_basic['ts_code'].isin(missing_codes)].copy()
                    missing_amount = last_amount[last_amount['ts_code'].isin(missing_codes)].copy()
                    
                    # 更新trade_date为当前日期
                    missing_basic = missing_basic.copy()
                    missing_basic['trade_date'] = date_str
                    missing_amount = missing_amount.copy()
                    missing_amount['trade_date'] = date_str
                    
                    # 合并
                    filled_basic = pd.concat([basic_day, missing_basic], ignore_index=True)
                    filled_amount = pd.concat([amount_day, missing_amount], ignore_index=True) if amount_day is not None else last_amount
                    
                    last_basic = filled_basic.copy()
                    last_amount = filled_amount.copy() if filled_amount is not None else last_amount
                    filled_basic_idx[date_str] = filled_basic
                    if filled_amount is not None:
                        filled_amount_idx[date_str] = filled_amount
                else:
                    filled_basic_idx[date_str] = basic_day
                    if amount_day is not None:
                        filled_amount_idx[date_str] = amount_day
            else:
                # 当日无数据，完全使用上次数据（更新日期）
                if last_basic is not None:
                    filled_b = last_basic.copy()
                    filled_b['trade_date'] = date_str
                    filled_basic_idx[date_str] = filled_b
                    if last_amount is not None:
                        filled_a = last_amount.copy()
                        filled_a['trade_date'] = date_str
                        filled_amount_idx[date_str] = filled_a
        else:
            # 第一个日期且数据不足，只能用当日数据
            filled_basic_idx[date_str] = basic_day if basic_day is not None else pd.DataFrame()
            if amount_day is not None:
                filled_amount_idx[date_str] = amount_day
    
    logger.info("  前向填充完成: %d 个日期 (覆盖%dearliest-%dlater)" % 
                (len(filled_basic_idx), len(all_dates_sorted)-len(filled_basic_idx), len(all_dates_sorted)-len(filled_basic_idx)))

    logger.info("原始数据加载完成，耗时 %.1f 秒", time.time() - t0)
    return stock_list, basic, amount, close, filled_basic_idx, filled_amount_idx

# ─── 工具函数 ─────────────────────────────────────────────────────────────

def build_valid_codes_cache(stock_list, all_dates):
    """预先计算所有日期的valid_codes"""
    from pandas import Series
    
    logger.info("  build_valid_codes_cache: %d dates, %d stocks", len(all_dates), len(stock_list))
    
    # 预处理
    codes_s = stock_list['ts_code'].astype(str)
    list_dates_s = stock_list['list_date'].astype(str)
    
    mask = ~(codes_s.str.startswith('4') | codes_s.str.startswith('8'))
    mask &= (list_dates_s.str.len() == 8)
    valid_df = stock_list[mask].copy()
    logger.info("  过滤后有效股票: %d", len(valid_df))
    
    cache = {}
    for date_str in all_dates:
        try:
            date_i = int(date_str)
            cutoff = date_i // 10000 * 10000 + (date_i % 10000) - 250  # 近似250天前的日期
            # 过滤：上市天数 >= 250天（且不是4/8开头）
            mask_dates = valid_df['list_date'].astype(str).str[:8].apply(lambda x: int(x) <= cutoff if len(x) == 8 else False)
            vs = set(valid_df[mask_dates]['ts_code'])
            cache[str(date_str)] = vs
        except Exception as e:
            print(f"WARNING: cache[{date_str}] failed: {e}", flush=True)
            cache[str(date_str)] = set()
    
    total = sum(len(v) for v in cache.values())
    avg = total // max(len(cache), 1)
    print(f"CACHE_BUILT: {len(cache)} dates, avg {avg} codes/days", flush=True)
    logger.info("  缓存完成: %d dates, 平均每日期 %d 只股票", len(cache), avg)
    return cache

def get_valid_codes(stock_list, trade_date, cache=None):
    """获取某日期有效股票列表（使用缓存）
    
    不再过滤上市天数——直接用当日有数据的股票，按市值排序取最小1000只。
    250天上市过滤改为仅过滤4/8开头和无效list_date。
    """
    if cache is not None and trade_date in cache:
        return list(cache[trade_date])
    # fallback - no listing date filter
    date_str = str(trade_date)
    valid = []
    for _, row in stock_list.iterrows():
        code = row['ts_code']
        if code.startswith('4') or code.startswith('8'):
            continue
        list_date = str(row.get('list_date', ''))
        if not list_date or len(list_date) != 8:
            continue
        valid.append(code)
    return valid

def get_5d_turnover(basic_df, codes, trade_date):
    """近5日换手率均值（向量化版本，大幅加速）"""
    if not codes:
        return np.nan, {}
    date_str = str(trade_date)
    
    # 获取近5个交易日（使用预索引的dates排序）
    dates_all = sorted(basic_df['trade_date'].unique())
    idx = dates_all.index(date_str) if date_str in dates_all else len(dates_all) - 1
    past_5 = dates_all[max(0, idx-4):idx+1]
    
    codes_set = set(codes)
    
    # 一次性获取近5日数据，用merge做批量查询
    sub_5d = basic_df[basic_df['trade_date'].isin(past_5)]
    sub_5d = sub_5d[sub_5d['ts_code'].isin(codes_set)]
    
    if sub_5d.empty:
        return np.nan, {}
    
    # 计算每只股票近5日均值
    avg_turnover = sub_5d.groupby('ts_code')['turnover_rate'].mean()
    
    # 全局均值
    return float(avg_turnover.mean()), dict(avg_turnover)

def rolling_percentile(series, window=150):
    """Rolling percentile rank over last `window` data points (≈3 years for 5-day sampling)
    
    Replaces expanding percentile to avoid historical data skew and reduce spike artifacts.
    """
    res = []
    for i, v in enumerate(series):
        start = max(0, i - window + 1)
        window_vals = series.iloc[start:i+1]
        rank = (window_vals <= v).sum() / len(window_vals)
        res.append(rank)
    return pd.Series(res, index=series.index)

# ─── 单日计算 ───────────────────────────────────────────────────────────

def calc_one_period(task):
    """计算单个日期的微盘指标（使用预索引数据）"""
    trade_date = task['trade_date']
    date_str = str(trade_date)
    try:
        cache = task.get('valid_cache')
        valid_codes = get_valid_codes(task['stock_list'], date_str, cache)
        if len(valid_codes) < 1000:
            return {'status': 'fail', 'trade_date': date_str, 'reason': '股票不足'}

        # 使用预索引的字典，O(1)查询
        basic_day = task['basic_idx'].get(date_str)
        amount_day = task['amount_idx'].get(date_str)

        if basic_day is None or amount_day is None or basic_day.empty or amount_day.empty:
            return {'status': 'fail', 'trade_date': date_str, 'reason': '数据空'}

        basic_day = basic_day.rename(columns={'total_mv': 'market_cap'})
        basic_day['market_cap'] = basic_day['market_cap'] / 10000.0

        val_df = basic_day.set_index('ts_code')
        val_df['amount'] = amount_day.set_index('ts_code')['amount']
        val_df = val_df.dropna(subset=['market_cap', 'amount']).reset_index()
        val_df.rename(columns={'ts_code': 'code'}, inplace=True)

        # 过滤有效股票（上市250天 + 排除4/8开头）
        valid_set = set(valid_codes)
        val_df = val_df[val_df['code'].isin(valid_set)]

        # 跳过股票数不足1000的日期（数据不完整）
        if len(val_df) < 1000:
            return {'status': 'fail', 'trade_date': date_str, 'reason': f'有效股票{len(val_df)}<1000，数据不完整'}

        val_df = val_df.sort_values('market_cap')
        micro_df = val_df.head(1000)

        micro_median = micro_df['market_cap'].median()
        all_median = val_df['market_cap'].median()
        relative_ratio = micro_median / all_median if all_median > 0 else np.nan

        micro_turnover, _ = get_5d_turnover(task['basic'], micro_df['code'].tolist(), date_str)
        all_turnover, _ = get_5d_turnover(task['basic'], val_df['code'].tolist(), date_str)
        crowding_ratio = micro_turnover / all_turnover if (all_turnover and all_turnover > 0) else np.nan

        micro_amount = micro_df['amount'].sum()
        all_amount = val_df['amount'].sum()
        amount_crowding_ratio = micro_amount / all_amount if all_amount > 0 else np.nan

        pe_vals = micro_df['pe'].dropna()
        pb_vals = micro_df['pb'].dropna()
        pe_median = float(pe_vals.median()) if len(pe_vals) > 0 else np.nan
        pb_median = float(pb_vals.median()) if len(pb_vals) > 0 else np.nan

        return {
            'status': 'ok',
            'rec': {
                'date': date_str,
                'micro_median': round(float(micro_median), 2),
                'all_median': round(float(all_median), 2),
                'relative_ratio': round(float(relative_ratio), 4),
                'crowding_ratio': round(float(crowding_ratio), 4),
                'amount_crowding_ratio': round(float(amount_crowding_ratio), 4),
                'pe_median': round(pe_median, 2) if not np.isnan(pe_median) else np.nan,
                'pb_median': round(pb_median, 2) if not np.isnan(pb_median) else np.nan,
                'avg_np_growth': np.nan,
            },
            'codes': micro_df['code'].tolist(),
        }
    except Exception as e:
        return {'status': 'fail', 'trade_date': date_str, 'reason': str(e)}

# ─── Phase1 主函数 ───────────────────────────────────────────────────────

def phase1():
    """Phase1: 并行计算所有交易日指标"""
    logger.info("=== Phase1: 计算所有交易日指标 ===")
    t0 = time.time()

    stock_list, basic, amount, close, basic_idx, amount_idx = load_raw_data()

    # 获取所有交易日（从daily_basic的日期列表）
    all_dates = sorted(basic['trade_date'].unique())
    logger.info("共 %d 个交易日，全部计算", len(all_dates))
    
    # 预计算所有日期的valid_codes（向量化，大幅加速）
    logger.info("预计算valid_codes缓存...")
    valid_cache = build_valid_codes_cache(stock_list, all_dates)
    logger.info("  缓存完成，每个日期约 %d 只股票", 
                int(sum(len(v) for v in valid_cache.values()) / len(all_dates)))

    # 串行处理以支持前向填充 micro_stocks
    tasks = [{'trade_date': d, 'stock_list': stock_list, 
              'basic': basic, 'amount': amount,
              'basic_idx': basic_idx, 'amount_idx': amount_idx,
              'valid_cache': valid_cache} for d in all_dates]
    records = []
    micro_stocks_by_date = {}
    prev_micro_codes = None  # 上一个成功日期的micro_stocks

    done = 0
    for task in tasks:
        # 如果有 prev_micro_codes，传入 task（用于前向填充）
        if prev_micro_codes is not None:
            task['prev_micro_codes'] = prev_micro_codes
        
        result = calc_one_period(task)
        if result['status'] == 'ok':
            records.append(result['rec'])
            micro_stocks_by_date[result['rec']['date']] = result['codes']
            prev_micro_codes = result['codes']  # 更新prev
        else:
            # 失败：用 prev_micro_codes 前向填充
            if prev_micro_codes is not None:
                date_str = str(task['trade_date'])
                logger.info("  前向填充 %s (上期 %d 只股票)", date_str, len(prev_micro_codes))
                # 用上期 micro_stocks 构造一个 proxy 记录
                # 需要重新计算：取上期股票在当日的 market_cap 数据
                basic_day = task['basic_idx'].get(date_str)
                amount_day = task['amount_idx'].get(date_str)
                if basic_day is not None and len(basic_day) > 0:
                    basic_day = basic_day.rename(columns={'total_mv': 'market_cap'})
                    basic_day['market_cap'] = basic_day['market_cap'] / 10000.0
                    val_df = basic_day.set_index('ts_code')
                    if amount_day is not None:
                        val_df['amount'] = amount_day.set_index('ts_code')['amount']
                    val_df = val_df.dropna(subset=['market_cap']).reset_index()
                    val_df.rename(columns={'ts_code': 'code'}, inplace=True)
                    
                    # 用上期micro_stocks过滤
                    proxy_df = val_df[val_df['code'].isin(set(prev_micro_codes))]
                    if len(proxy_df) >= 50:  # 至少50只才有效
                        proxy_df = proxy_df.sort_values('market_cap')
                        micro_df = proxy_df.head(min(1000, len(proxy_df)))
                        
                        micro_median = micro_df['market_cap'].median()
                        all_median = val_df['market_cap'].median()
                        relative_ratio = micro_median / all_median if all_median > 0 else np.nan
                        
                        micro_turnover = micro_df['turnover_rate'].median() if 'turnover_rate' in micro_df.columns else np.nan
                        all_turnover = val_df['turnover_rate'].median() if 'turnover_rate' in val_df.columns else np.nan
                        crowding_ratio = micro_turnover / all_turnover if (all_turnover and not np.isnan(all_turnover)) else np.nan
                        
                        micro_amount = micro_df['amount'].sum() if 'amount' in micro_df.columns else np.nan
                        all_amount = val_df['amount'].sum() if 'amount' in val_df.columns else np.nan
                        amount_crowding_ratio = micro_amount / all_amount if (all_amount and not np.isnan(all_amount)) else np.nan
                        
                        pe_vals = micro_df['pe'].dropna()
                        pb_vals = micro_df['pb'].dropna()
                        pe_median = float(pe_vals.median()) if len(pe_vals) > 0 else np.nan
                        pb_median = float(pb_vals.median()) if len(pb_vals) > 0 else np.nan
                        
                        proxy_rec = {
                            'date': date_str,
                            'micro_median': round(float(micro_median), 2) if not np.isnan(micro_median) else np.nan,
                            'all_median': round(float(all_median), 2) if not np.isnan(all_median) else np.nan,
                            'relative_ratio': round(float(relative_ratio), 4) if not np.isnan(relative_ratio) else np.nan,
                            'crowding_ratio': round(float(crowding_ratio), 4) if not np.isnan(crowding_ratio) else np.nan,
                            'amount_crowding_ratio': round(float(amount_crowding_ratio), 4) if not np.isnan(amount_crowding_ratio) else np.nan,
                            'pe_median': round(pe_median, 2) if not np.isnan(pe_median) else np.nan,
                            'pb_median': round(pb_median, 2) if not np.isnan(pb_median) else np.nan,
                            'avg_np_growth': np.nan,
                        }
                        records.append(proxy_rec)
                        micro_stocks_by_date[date_str] = list(proxy_df['code'])
                        prev_micro_codes = list(proxy_df['code'])
                        logger.info("  前向填充成功: %s micro_median=%.2f", date_str, micro_median)
                    else:
                        logger.info("  前向填充跳过: %s 仅 %d 只股票", date_str, len(proxy_df))
                else:
                    logger.info("  前向填充跳过: %s 无数据", date_str)
            # else: 第一个日期就失败，无法前向填充，跳过
        
        done += 1
        if done % 50 == 0:
            logger.info("Phase1进度: %d/%d (成功 %d 期)", done, len(all_dates), len(records))

    logger.info("Phase1完成: 成功 %d 期，耗时 %.0f 秒", len(records), time.time() - t0)

    # ── 分位计算 ──
    result = pd.DataFrame(records).sort_values('date').reset_index(drop=True)
    
    # 稀疏日期标记（股票数<3000的数据不完整）
    # 这些日期的relative_ratio会因为股票数少而被人为拉高，不反映真实市场情况
    sparse_dates = set()
    for _, row in result.iterrows():
        date_str = str(row['date'])
        basic_day = basic_idx.get(date_str)
        if basic_day is not None and len(basic_day) < 3000:
            sparse_dates.add(date_str)
    
    if sparse_dates:
        logger.info("  稀疏日期（<3000股票）%d个，将用线性插值填充: %s", 
                    len(sparse_dates), sorted(sparse_dates)[:5])
    
    # 对四个核心指标做线性插值填充稀疏日期
    # 再用填充后的数据计算分位——这样稀疏日期的异常值不会污染其他日期的分位
    for col in ['micro_median', 'relative_ratio', 'crowding_ratio', 'amount_crowding_ratio']:
        s = result[col].copy()
        # 线性插值：只对稀疏日期插值，其他日期保持原值
        s_interp = s.copy()
        sparse_idx = [i for i, d in enumerate(result['date'].astype(str)) if str(d) in sparse_dates]
        if sparse_idx:
            s_interp.iloc[sparse_idx] = np.nan  # 先设为NaN
            s_interp = s_interp.interpolate(method='linear', limit_area='inside')
            # 确保稀疏日期都被填充了
            for idx in sparse_idx:
                if pd.isna(s_interp.iloc[idx]):
                    # 如果插值失败，用前后最近正常日期的值
                    left_vals = s_interp.iloc[:idx].dropna()
                    right_vals = s_interp.iloc[idx+1:].dropna()
                    if len(left_vals) > 0 and len(right_vals) > 0:
                        s_interp.iloc[idx] = (left_vals.iloc[-1] + right_vals.iloc[0]) / 2
                    elif len(left_vals) > 0:
                        s_interp.iloc[idx] = left_vals.iloc[-1]
                    elif len(right_vals) > 0:
                        s_interp.iloc[idx] = right_vals.iloc[0]
        result[col] = s_interp
    
    # 使用3年滚动窗口percentile
    WINDOW = 150
    for col in ['micro_median', 'relative_ratio', 'crowding_ratio', 'amount_crowding_ratio']:
        result[col + '_pct'] = rolling_percentile(result[col], window=WINDOW)
    
    result['cap_pct'] = result['relative_ratio_pct']
    result['score'] = (
        result['relative_ratio_pct'] * 0.50
        + result['crowding_ratio_pct'] * 0.25
        + result['amount_crowding_ratio_pct'] * 0.25
    )

    # ── Phase2: 等权指数 ──
    logger.info("Phase2: 计算等权指数...")
    dates_sorted = list(result['date'])
    # 用groupby快速构建 close_dict，比iterrows快10倍+
    close_dict = {}
    for d, grp in close.groupby('trade_date'):
        close_dict[str(d)] = dict(zip(grp['ts_code'], grp['close']))

    index_vals = [1000.0]
    for i in range(1, len(dates_sorted)):
        prev_date = dates_sorted[i - 1]
        curr_date = dates_sorted[i]
        prev_stocks = micro_stocks_by_date.get(prev_date, [])
        if not prev_stocks:
            index_vals.append(index_vals[-1])
            continue

        prev_close_list = [close_dict.get(prev_date, {}).get(s, np.nan) for s in prev_stocks]
        prev_close = pd.Series(prev_close_list, index=prev_stocks)

        curr_stocks = micro_stocks_by_date.get(curr_date, [])
        curr_close_all_list = [close_dict.get(curr_date, {}).get(s, np.nan) for s in curr_stocks]
        curr_close_all = pd.Series(curr_close_all_list, index=curr_stocks)

        missing = [s for s in prev_stocks if s not in curr_close_all.index]
        if missing:
            extra_list = [close_dict.get(curr_date, {}).get(s, np.nan) for s in missing]
            extra = pd.Series(extra_list, index=missing)
            curr_close = pd.concat([curr_close_all, extra])
        else:
            curr_close = curr_close_all

        common = [s for s in prev_stocks if s in prev_close.index and s in curr_close.index]
        rets = []
        for s in common:
            p_prev = prev_close[s]
            p_curr = curr_close[s]
            if p_prev > 0 and p_curr > 0:
                rets.append(p_curr / p_prev - 1.0)

        if rets:
            next_val = index_vals[-1] * (1.0 + np.mean(rets))
        else:
            next_val = index_vals[-1]
        index_vals.append(next_val)

    result['micro_index'] = index_vals

    # ── 写CSV ──
    csv_path = OUTPUT_DIR / 'weipan_metrics.csv'
    result.to_csv(csv_path, index=False, encoding='utf-8')
    logger.info("CSV写入完成: %d 期 → %s", len(result), csv_path)

    # ── Phase3: 生成图表 ──
    logger.info("Phase3: 生成图表...")
    from generators.gen_weipan_images import generate_all_images as gen_images
    gen_images()
    logger.info("=== 全部完成 ===")

    return result

if __name__ == '__main__':
    phase1()