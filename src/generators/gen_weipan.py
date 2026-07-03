#!/usr/bin/env python3
"""
微盘1000多维度分析 - 完全对齐 JoinQuant weipanweiduji.py 逻辑
支持全量并行重建（ThreadPoolExecutor），大幅加速数据生成
"""
import sys, os, re, json
from pathlib import Path
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd
import numpy as np
import threading

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / 'src'))
from utils.log_config import get_logger
logger = get_logger("微盘分析")

DATA_DIR = PROJECT_ROOT / 'data'
DATA_DIR.mkdir(exist_ok=True)
WEIPAN_CSV = DATA_DIR / 'weipan_metrics.csv'

import tushare as ts
pro = ts.pro_api()

import time as _time
_RATE_WINDOW = 60.0
_RATE_MAX = 180  # 限速200次/分，用180次留20次缓冲
_rate_history = []
_rate_lock = threading.Lock()
_last_call_time = [0.0]  # 上次API调用时间

# ─── 速率限制（固定延迟，确保不超过200次/分）────────────────────────────────

def _rate_limit():
    """全局速率限制：每次API调用后固定等待0.35秒，确保不超过200次/分"""
    with _rate_lock:
        now = _time.time()
        elapsed = now - _last_call_time[0]
        if elapsed < 0.35:
            _time.sleep(0.35 - elapsed)
        _last_call_time[0] = _time.time()

# ─── 工具函数 ────────────────────────────────────────────────────────────────

def get_all_trade_dates(start_date='20180101', end_date=None):
    if end_date is None:
        end_date = datetime.now().strftime('%Y%m%d')
    _rate_limit()
    df = pro.trade_cal(start_date=start_date, end_date=end_date,
                       fields='exchange,cal_date,is_open')
    df = df[df['is_open'] == 1]
    dates = sorted(df['cal_date'].tolist())
    sampled = dates[::5]
    logger.info("获取到 %d 个交易日，采样 %d 个", len(dates), len(sampled))
    return sampled

_stock_info_cache = None  # 全局缓存 stock_basic 信息（list_date, name, is_st）

def _get_stock_info():
    """"获取股票基本信息缓存（只查一次）"""
    global _stock_info_cache
    if _stock_info_cache is None:
        _rate_limit()
        _stock_info_cache = pro.stock_basic(
            list_status='L',
            fields='ts_code,list_date,name,is_st'
        )
    return _stock_info_cache

def get_stock_list(trade_date):
    """每天重新获取当日有效股票池（对齐JQ每日get_all_securities）

    JQ逻辑：get_all_securities(date=date) 返回该日期实际可交易的所有股票（含已退市）。
    Tushare方案：用 daily_basic(trade_date) 获取该日期有数据的股票（已退市股无该日数据），
    再用 stock_basic 的 list_date 过滤未上市股票，is_st + name 前缀过滤 ST。
    """
    _rate_limit()
    basic_df = pro.daily_basic(
        trade_date=trade_date,
        fields='ts_code'
    )
    if basic_df is None or basic_df.empty:
        return []
    valid_codes = set(basic_df['ts_code'].tolist())

    info_df = _get_stock_info()
    codes = []
    for _, row in info_df.iterrows():
        code = row['ts_code']
        if code not in valid_codes:
            continue
        if code.startswith('4') or code.startswith('8'):
            continue
        list_date = str(row.get('list_date', ''))
        if not list_date or len(list_date) != 8:
            continue
        try:
            days = (datetime.strptime(trade_date, '%Y%m%d')
                    - datetime.strptime(list_date, '%Y%m%d')).days
        except ValueError:
            continue
        if days < 250:
            continue
        # ST过滤：先用 is_st 字段，再用名称前缀兜底
        if row.get('is_st') == 1:
            continue
        name = str(row.get('name', ''))
        if name.startswith('*ST') or name.startswith('ST'):
            continue
        codes.append(code)
    return codes



def get_daily_basic(trade_date):
    _rate_limit()
    return pro.daily_basic(
        trade_date=trade_date,
        fields='ts_code,trade_date,turnover_rate,pe,pb,total_mv'
    )

def get_daily_amount(trade_date):
    _rate_limit()
    return pro.daily(trade_date=trade_date, fields='ts_code,amount')

def get_5d_turnover_ratio(codes, trade_date):
    """近5个交易日换手率均值（mean of per_stock_5d_mean，对齐JQ）
    
    JQ逻辑：对过去5个交易日各取一次valuation.turnover_ratio，
    每只股票算5日均值，然后对所有股票取MEAN（不是median）。
    Tushare用daily_basic.turnover_rate代替。
    """
    if not codes:
        return np.nan, {}
    _rate_limit()
    td_df = pro.trade_cal(end_date=trade_date, fields='cal_date,is_open')
    td_df = td_df[td_df['is_open'] == 1]
    past_5_days = sorted(td_df['cal_date'].tolist())[-5:]

    all_rows = []
    for d in past_5_days:
        _rate_limit()
        try:
            chunk = pro.daily_basic(trade_date=d, fields='ts_code,turnover_rate')
            if chunk is not None and not chunk.empty:
                sub = chunk[chunk['ts_code'].isin(codes)]
                all_rows.append(sub.set_index('ts_code')['turnover_rate'])
        except Exception:
            continue

    if not all_rows:
        return np.nan, {}
    tr_df = pd.concat(all_rows, axis=1, sort=False)
    # JQ: tr_5d_mean = per_stock.mean(axis=1), then micro_tr = micro['tr'].mean()
    # 这里返回 (全局mean, per_stock_dict)，caller用 .mean() 而不是 .median()
    per_stock_mean = tr_df.mean(axis=1)
    return float(per_stock_mean.mean()), dict(per_stock_mean)

def get_np_growth(codes, trade_date):
    if not codes:
        return np.nan
    all_vals = []
    chunks = [codes[i:i+500] for i in range(0, len(codes), 500)]
    for chunk in chunks:
        _rate_limit()
        try:
            # Tushare没有JQ的inc_net_profit_to_shareholders_year_on_year字段，
            # 用 netprofit_yoy（净利润增速）代替，是不同的指标
            df = pro.fina_indicator(
                ts_code=','.join(chunk),
                end_date=trade_date,
                fields='ts_code,netprofit_yoy'
            )
            if df is not None and not df.empty:
                vals = df['netprofit_yoy'].dropna()
                all_vals.extend(vals.tolist())
        except Exception as e:
            logger.warning("fina_indicator 查询失败: %s", e)
            continue
    if not all_vals:
        return np.nan
    return float(np.nanmedian(all_vals))

def get_close_prices(codes, trade_date):
    """获取指定股票在当日的收盘价（分批，每批500）"""
    if not codes:
        return pd.Series(dtype=float)
    all_rows = []
    chunks = [codes[i:i+500] for i in range(0, len(codes), 500)]
    for chunk in chunks:
        _rate_limit()
        try:
            df = pro.daily(ts_code=','.join(chunk), trade_date=trade_date, fields='ts_code,close')
            if df is not None and not df.empty:
                all_rows.append(df)
        except Exception:
            continue
    if not all_rows:
        return pd.Series(dtype=float)
    return pd.concat(all_rows, ignore_index=True).set_index('ts_code')['close']

# ─── 历史分位函数 ───────────────────────────────────────────────────────────

def percentile_rank(series):
    res, values = [], []
    for v in series:
        values.append(v)
        res.append(pd.Series(values).rank(pct=True).iloc[-1])
    return pd.Series(res, index=series.index)

# ─── 单日计算（返回结果dict，不含指数）────────────────────────────────────────

def calc_one_period(task):
    """
    并行 worker：计算单个日期的指标
    task = {'trade_date': str}
    返回 {'status': 'ok', 'rec': dict, 'codes': list} 或 {'status': 'fail', 'trade_date': str}
    """
    trade_date = task['trade_date']
    try:
        valid_codes = get_stock_list(trade_date)
        if len(valid_codes) < 1000:
            logger.warning("%s 有效股票不足: %d", trade_date, len(valid_codes))
            return {'status': 'fail', 'trade_date': trade_date, 'reason': '股票不足'}

        basic_df = get_daily_basic(trade_date)
        if basic_df is None or basic_df.empty:
            return {'status': 'fail', 'trade_date': trade_date, 'reason': 'daily_basic空'}

        amount_df = get_daily_amount(trade_date)
        if amount_df is None or amount_df.empty:
            return {'status': 'fail', 'trade_date': trade_date, 'reason': 'daily空'}

        basic_df = basic_df.rename(columns={'total_mv': 'market_cap', 'turnover_rate': 'turnover_ratio'})
        basic_df['market_cap'] = basic_df['market_cap'] / 10000.0

        val_df = basic_df.set_index('ts_code')
        val_df['amount'] = amount_df.set_index('ts_code')['amount']
        val_df = val_df.dropna(subset=['market_cap', 'amount']).reset_index()
        val_df.rename(columns={'ts_code': 'code'}, inplace=True)

        valid_set = set(valid_codes)
        val_df = val_df[val_df['code'].isin(valid_set)]
        if len(val_df) < 1000:
            return {'status': 'fail', 'trade_date': trade_date, 'reason': '过滤后不足'}

        val_df = val_df.sort_values('market_cap')
        micro_df = val_df.head(1000)

        micro_median = micro_df['market_cap'].median()
        all_median = val_df['market_cap'].median()
        relative_ratio = micro_median / all_median if all_median > 0 else np.nan

        # 近5日换手率均值
        micro_turnover, _ = get_5d_turnover_ratio(micro_df['code'].tolist(), trade_date)
        all_turnover, _ = get_5d_turnover_ratio(val_df['code'].tolist(), trade_date)
        crowding_ratio = micro_turnover / all_turnover if (all_turnover and all_turnover > 0) else np.nan

        micro_amount = micro_df['amount'].sum()
        all_amount = val_df['amount'].sum()
        amount_crowding_ratio = micro_amount / all_amount if all_amount > 0 else np.nan

        pe_vals = micro_df['pe'].dropna()
        pb_vals = micro_df['pb'].dropna()
        pe_median = float(pe_vals.median()) if len(pe_vals) > 0 else np.nan
        pb_median = float(pb_vals.median()) if len(pb_vals) > 0 else np.nan

        micro_codes = micro_df['code'].tolist()
        avg_np_growth = get_np_growth(micro_codes, trade_date)

        rec = {
            'date': trade_date,
            'micro_median': round(float(micro_median), 2),
            'all_median': round(float(all_median), 2),
            'relative_ratio': round(float(relative_ratio), 4),
            'crowding_ratio': round(float(crowding_ratio), 4),
            'amount_crowding_ratio': round(float(amount_crowding_ratio), 4),
            'pe_median': round(pe_median, 2) if not np.isnan(pe_median) else np.nan,
            'pb_median': round(pb_median, 2) if not np.isnan(pb_median) else np.nan,
            'avg_np_growth': round(float(avg_np_growth), 2) if not np.isnan(avg_np_growth) else np.nan,
            '_micro_codes': micro_codes,
        }
        logger.info("✓ %s 完成", trade_date)
        return {'status': 'ok', 'rec': rec, 'codes': micro_codes}

    except Exception as e:
        logger.warning("✗ %s 异常: %s", trade_date, e)
        return {'status': 'fail', 'trade_date': trade_date, 'reason': str(e)}

# ─── 全量重建（并行版）────────────────────────────────────────────────────────

def rebuild():
    """
    三层流水线并行：
      Phase1: 并行计算所有期的基础指标（ThreadPoolExecutor）
      Phase2: 并行抓取所有需要的收盘价
      Phase3: 串行计算等权指数 → 写CSV
    """
    logger.info("=== 开始全量重建（并行版）===")
    trade_dates = get_all_trade_dates('20180101')
    if not trade_dates:
        return

    WORKERS = 1
    logger.info("Phase1: 并行计算 %d 期基础指标（%d线程）...", len(trade_dates), WORKERS)

    # Phase1: 并行计算所有期
    tasks = [{'trade_date': d} for d in trade_dates]
    records = []
    micro_stocks_by_date = {}
    failed = []

    def do_one(task):
        result = calc_one_period(task)
        return result

    with ThreadPoolExecutor(max_workers=WORKERS) as executor:
        futures = {executor.submit(do_one, t): t for t in tasks}
        done = 0
        for future in as_completed(futures):
            result = future.result()
            if result['status'] == 'ok':
                records.append(result['rec'])
                micro_stocks_by_date[result['rec']['date']] = result['codes']
            else:
                failed.append((result['trade_date'], result.get('reason')))
            done += 1
            if done % 50 == 0:
                logger.info("Phase1进度: %d/%d (失败 %d)", done, len(trade_dates), len(failed))

    # 重试失败的日期（串行，确保成功）
    if failed:
        logger.info("Phase1: 重试 %d 个失败日期...", len(failed))
        retry_failed = []
        for d, reason in failed:
            result = calc_one_period({'trade_date': d})
            if result['status'] == 'ok':
                records.append(result['rec'])
                micro_stocks_by_date[result['rec']['date']] = result['codes']
                logger.info("  ✓ %s 重试成功", d)
            else:
                retry_failed.append((d, result.get('reason')))
                logger.warning("  ✗ %s 重试仍失败: %s", d, result.get('reason'))
        failed = retry_failed

    logger.info("Phase1完成: 成功 %d, 失败 %d", len(records), len(failed))
    if not records:
        logger.error("Phase1无有效数据，退出")
        return

    # 等到所有日期都成功后再继续（防止Phase2/Phase3在串行重试期间抢先启动）
    all_dates_in_records = set(r['date'] for r in records)
    all_trade_dates = set(get_all_trade_dates('20180101'))
    if all_dates_in_records != all_trade_dates:
        missing = all_trade_dates - all_dates_in_records
        logger.warning("Phase1还有 %d 个日期缺失，等待串行重试完成...: %s", len(missing), sorted(missing)[:5])
        # 串行补算所有缺失的日期
        for d in sorted(missing):
            result = calc_one_period({'trade_date': d})
            if result['status'] == 'ok':
                records.append(result['rec'])
                all_dates_in_records.add(result['rec']['date'])
                logger.info("  ✓ 补算成功 %s", d)
            else:
                logger.warning("  ✗ 补算失败 %s: %s", d, result.get('reason'))
        logger.info("补算完成，总成功 %d 期", len(records))

    # 按日期排序
    result = pd.DataFrame(records).sort_values('date').reset_index(drop=True)

    # Phase2: 批量抓取收盘价（按年份分批）
    # Tushare的pro.daily对长日期范围返回不完整数据，
    # 因此按年份分批查询，确保历史数据不丢失
    dates_sorted = list(result['date'])
    logger.info("Phase2: 批量抓取收盘价（%d期）...", len(dates_sorted))

    # 收集所有需要的股票
    all_stocks_needed = set()
    for date, codes in micro_stocks_by_date.items():
        all_stocks_needed.update(codes)
    all_stocks_needed = sorted(all_stocks_needed)
    logger.info("Phase2: 共需 %d 只股票的价格", len(all_stocks_needed))

    # 按年份分批查询（避免长日期范围导致Tushare数据截断）
    year_chunks = []
    first_year = int(dates_sorted[0][:4])
    last_year = int(dates_sorted[-1][:4])
    for year in range(first_year, last_year + 1):
        year_chunks.append((f'{year}0101', f'{year}1231'))
    # 最后一期延续到最后一个日期
    year_chunks[-1] = (year_chunks[-1][0], dates_sorted[-1])

    stock_close_data = {}  # stock -> {date -> price}

    for yc_idx, (y_start, y_end) in enumerate(year_chunks):
        # 按股票分小批（每批300只，减少单次请求规模）
        stock_chunks = [all_stocks_needed[i:i+300] for i in range(0, len(all_stocks_needed), 300)]
        for sc_idx, chunk in enumerate(stock_chunks):
            _rate_limit()
            try:
                df = pro.daily(
                    ts_code=','.join(chunk),
                    start_date=y_start,
                    end_date=y_end,
                    fields='ts_code,trade_date,close'
                )
                if df is not None and not df.empty:
                    for _, row in df.iterrows():
                        s = row['ts_code']
                        d = str(row['trade_date'])
                        if s not in stock_close_data:
                            stock_close_data[s] = {}
                        stock_close_data[s][d] = row['close']
            except Exception as e:
                logger.warning("  [%d/%d] 年份%s 股票批次%d 失败: %s", yc_idx+1, len(year_chunks), y_start[:4], sc_idx, e)
        logger.info("Phase2: year %d/%d (%s-%s) done", yc_idx+1, len(year_chunks), y_start, y_end)

    logger.info("Phase2完成，收盘价缓存 %d 只股票", len(stock_close_data))

    # 用批量数据构建 close_results
    close_results = {}
    for i, curr_date in enumerate(dates_sorted):
        prev_date = dates_sorted[i - 1] if i > 0 else None
        curr_stocks = micro_stocks_by_date.get(curr_date, [])
        prev_stocks = micro_stocks_by_date.get(prev_date, []) if prev_date else []

        for s in curr_stocks:
            d = stock_close_data.get(s, {}).get(curr_date, np.nan)
            if not np.isnan(d):
                close_results[(curr_date, s)] = d

        if prev_date:
            for s in prev_stocks:
                if s not in curr_stocks:
                    d = stock_close_data.get(s, {}).get(curr_date, np.nan)
                    if not np.isnan(d):
                        close_results[(curr_date, s)] = d

    logger.info("Phase2: 收盘价索引构建完成，共 %d 条", len(close_results))

    # Phase3: 串行计算等权指数
    logger.info("Phase3: 计算等权指数...")
    index_vals = [1000.0]

    for i in range(1, len(dates_sorted)):
        prev_date = dates_sorted[i - 1]
        curr_date = dates_sorted[i]

        prev_stocks = micro_stocks_by_date.get(prev_date, [])
        if not prev_stocks:
            index_vals.append(index_vals[-1])
            continue

        # 上期收盘价
        prev_close_list = [close_results.get((prev_date, s), np.nan) for s in prev_stocks]
        prev_close = pd.Series(prev_close_list, index=prev_stocks)

        # 本期收盘价（含本期成分股）
        curr_stocks = micro_stocks_by_date.get(curr_date, [])
        curr_close_all_list = [close_results.get((curr_date, s), np.nan) for s in curr_stocks]
        curr_close_all = pd.Series(curr_close_all_list, index=curr_stocks)

        # 补齐上期成分股中不在本期名单的
        missing = [s for s in prev_stocks if s not in curr_close_all.index]
        if missing:
            extra_list = [close_results.get((curr_date, s), np.nan) for s in missing]
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

        if i % 50 == 0:
            logger.info("Phase3进度: %d/%d", i, len(dates_sorted))

    result['micro_index'] = index_vals

    # 分位计算
    for col in ['micro_median', 'relative_ratio', 'crowding_ratio', 'amount_crowding_ratio']:
        result[col + '_pct'] = percentile_rank(result[col])

    # 市值分位：JQ cap_pct = percentile_rank(relative_ratio)
    result['cap_pct'] = result['relative_ratio_pct']

    result['score'] = (
        result['relative_ratio_pct'] * 0.50
        + result['crowding_ratio_pct'] * 0.25
        + result['amount_crowding_ratio_pct'] * 0.25
    )

    save_cols = [c for c in result.columns
                 if c not in ('_micro_codes', 'micro_median_pct', 'relative_ratio_pct',
                              'crowding_ratio_pct', 'amount_crowding_ratio_pct')]
    result[save_cols].to_csv(WEIPAN_CSV, index=False, encoding='utf-8')
    logger.info("全量写入完成: %d 期 → %s", len(records), WEIPAN_CSV)

    # 生成7张图表
    logger.info("开始生成图表...")
    gen_images()


# ─── 增量追加 ────────────────────────────────────────────────────────────────

def append_today():
    today = datetime.now().strftime('%Y%m%d')

    if WEIPAN_CSV.exists():
        existing = pd.read_csv(WEIPAN_CSV, dtype={'date': str})
        recorded = set(existing['date'].astype(str).tolist())
    else:
        existing = pd.DataFrame(columns=['date','micro_median','all_median',
                                           'relative_ratio','crowding_ratio',
                                           'amount_crowding_ratio','pe_median','pb_median',
                                           'avg_np_growth','score','micro_index'])
        recorded = set()

    candidates = []
    for delta in range(0, 4):
        d = (datetime.now() - timedelta(days=delta)).strftime('%Y%m%d')
        candidates.append(d)

    new_dates = [d for d in candidates if d not in recorded]
    if not new_dates:
        logger.info("今日(%s)数据已存在，跳过", today)
        return

    logger.info("增量补入: %s", new_dates)
    records = []
    for d in new_dates:
        result = calc_one_period({'trade_date': d})
        if result['status'] == 'ok':
            records.append(result['rec'])

    if not records:
        return

    new_df = pd.DataFrame(records)
    result = pd.concat([existing, new_df], ignore_index=True)
    result = result.drop_duplicates(subset=['date']).sort_values('date').reset_index(drop=True)

    for col in ['micro_median', 'relative_ratio', 'crowding_ratio', 'amount_crowding_ratio']:
        result[col + '_pct'] = percentile_rank(result[col])

    # 市值分位：JQ cap_pct = percentile_rank(relative_ratio)
    result['cap_pct'] = result['relative_ratio_pct']
    result['score'] = (
        result['relative_ratio_pct'] * 0.50
        + result['crowding_ratio_pct'] * 0.25
        + result['amount_crowding_ratio_pct'] * 0.25
    )

    if '_micro_codes' in result.columns and len(result) >= 2:
        last_codes_str = result.iloc[-2]['_micro_codes']
        last_codes = eval(last_codes_str) if isinstance(last_codes_str, str) else (last_codes_str or [])
        if last_codes:
            prev_date = result.iloc[-2]['date']
            curr_date = result.iloc[-1]['date']
            prev_close = get_close_prices(last_codes, str(int(prev_date)))
            curr_close = get_close_prices(last_codes, str(int(curr_date)))
            common = [s for s in last_codes if s in prev_close.index and s in curr_close.index]
            rets = []
            for s in common:
                p_prev = prev_close[s]
                p_curr = curr_close[s]
                if p_prev > 0 and p_curr > 0:
                    rets.append(p_curr / p_prev - 1.0)
            if rets:
                prev_idx = result.iloc[-2]['micro_index']
                if pd.isna(prev_idx):
                    prev_idx = 1000.0
                new_idx = float(prev_idx) * (1.0 + np.mean(rets))
                result.loc[result.index[-1], 'micro_index'] = new_idx

    save_cols = [c for c in result.columns
                 if c not in ('_micro_codes', 'micro_median_pct', 'relative_ratio_pct',
                              'crowding_ratio_pct', 'amount_crowding_ratio_pct')]
    result[save_cols].to_csv(WEIPAN_CSV, index=False, encoding='utf-8')
    logger.info("增量追加完成: %d 天 → %s", len(records), WEIPAN_CSV)

    # 生成图表
    logger.info("生成图表...")
    gen_images()


# ─── CLI ─────────────────────────────────────────────────────────────────────

# 导入图片生成器
sys.path.insert(0, str(PROJECT_ROOT / 'src' / 'generators'))
from gen_weipan_images import generate_all_images as gen_images

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='微盘1000多维度分析')
    parser.add_argument('--mode', choices=['rebuild', 'append'], default='append',
                        help='rebuild=全量重建2018至今, append=仅追加今天(默认)')
    args = parser.parse_args()

    if args.mode == 'rebuild':
        rebuild()
    else:
        append_today()