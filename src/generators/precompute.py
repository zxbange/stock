#!/usr/bin/env python3
"""
预计算K线指标数据，支持三种模式：
  --mode daily   : 日线指标
  --mode weekly  : 周K+月K
  --mode all     : 三种都跑
输出统一到 daily_result/today/indicators/

支持两种数据源：
  --source stock : 从 data/kline/*.csv 读取（默认）
  --source etf   : 从 data/etf/*.csv 读取

特殊模式：
  --from-results : 从 today/result_*.txt 读取已选股代码，只预计算这些
"""
import os, json, sys, glob, argparse, concurrent.futures, re
from pathlib import Path
from pathlib import Path
import pandas as pd
import tushare as ts
import time

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
BASE = PROJECT_ROOT
from utils.log_config import get_logger
logger = get_logger("预计算指标")


def get_api():
    token = ts.get_token()
    pro = ts.pro_api(token)
    return pro


def rate_call(func, *args, **kwargs):
    """带速率限制的API调用（precompute阶段，低频可复用）"""
    return func(*args, **kwargs)  # 直接调，无严格限速

DATA_DIR_STOCK = str(PROJECT_ROOT / 'data/kline')
DATA_DIR_ETF   = str(PROJECT_ROOT / 'data/etf')
TODAY_DIR      = '/home/bange/stock/daily_result/today'
OUT_DIR        = os.path.join(TODAY_DIR, 'indicators')
os.makedirs(OUT_DIR, exist_ok=True)

# ─── 共用指标计算 ───────────────────────────────────────────────────────────

def ema(arr, n):
    k = 2/(n+1)
    r = [arr[0]]
    for i in range(1, len(arr)):
        r.append(arr[i]*k + r[-1]*(1-k))
    return r

def compute(data):
    close = [d['c'] for d in data]
    low   = [d['l'] for d in data]
    high  = [d['h'] for d in data]

    ma5   = [None]*(5-1)   + [sum(close[i-4:i+1])/5     for i in range(4, len(close))]
    ma10  = [None]*(10-1)  + [sum(close[i-9:i+1])/10   for i in range(9, len(close))]
    ma20  = [None]*(20-1)  + [sum(close[i-19:i+1])/20  for i in range(19, len(close))]
    ma30  = [None]*(30-1)  + [sum(close[i-29:i+1])/30  for i in range(29, len(close))]
    ma60  = [None]*(60-1)  + [sum(close[i-59:i+1])/60  for i in range(59, len(close))]
    ma120 = [None]*(120-1) + [sum(close[i-119:i+1])/120 for i in range(119, len(close))]
    ma240 = [None]*(240-1) + [sum(close[i-239:i+1])/240 for i in range(239, len(close))]

    e12 = ema(close, 12)
    e26 = ema(close, 26)
    dif  = [e12[i]-e26[i] for i in range(len(close))]
    dea_ = ema(dif, 9)
    macd = [(dif[i]-dea_[i])*2 for i in range(len(close))]

    n = 9
    K = [50.0]*len(close)
    D = [50.0]*len(close)
    for i in range(1, len(close)):
        ll = min(low[max(0,i-n+1):i+1])
        hh = max(high[max(0,i-n+1):i+1])
        rsv = 50 if hh==ll else (close[i]-ll)/(hh-ll)*100
        K[i] = 2/3*K[i-1] + 1/3*rsv
        D[i] = 2/3*D[i-1] + 1/3*K[i]
    J = [3*K[i]-2*D[i] for i in range(len(close))]

    return dict(
        ma5=ma5, ma10=ma10, ma20=ma20, ma30=ma30, ma60=ma60,
        ma120=ma120, ma240=ma240,
        dif=dif, dea=dea_, macd=macd, K=K, D=D, J=J
    )

# ─── 数据读取 ───────────────────────────────────────────────────────────────

def load_csv_stock(code):
    path = os.path.join(DATA_DIR_STOCK, f'{code}.csv')
    rows = []
    with open(path) as f:
        next(f)
        for line in f:
            c = line.strip().split(',')
            if len(c) < 10: continue
            rows.append({'time': c[1], 'o': float(c[2]), 'h': float(c[3]),
                         'l': float(c[4]), 'c': float(c[5]), 'v': float(c[9])})
    return rows

def load_csv_etf(code):
    """加载ETF日K线，CSV格式：ts_code,date,pre_close,open,high,low,close,change,pct_chg,volume,amount,adj_factor
    前复权公式: adj_price = raw_price × 当日因子 ÷ 最新因子
    效果: 把分拆/折算前价格压缩到分拆后水平，K线自然连续。

    ⚠️ 重要修复记录（2026-05-12）：
    最新因子必须取"距今最近日期"的因子，不能用max(factor)。
    原因：部分基金拆分导致历史因子数值反而大于最新因子，
    用max会导致历史价格被压缩过度，K线失真。"""
    path = os.path.join(DATA_DIR_ETF, f'{code}.csv')
    if not os.path.exists(path):
        return []

    # 读取CSV（adj_factor在最后一列col 11）
    rows_raw = []
    with open(path) as f:
        next(f)  # header
        for line in f:
            c = line.strip().split(',')
            if len(c) < 11:
                continue
            d = c[1]
            # d 可能是 YYYYMMDD 或 YYYY-MM-DD
            if '-' in d:
                date_fmt = d  # 已经是YYYY-MM-DD格式
            else:
                date_fmt = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
            # adj_factor在col 11（索引11），无则默认为1.0
            factor = float(c[11]) if len(c) > 11 and c[11] else 1.0
            rows_raw.append({
                'time': date_fmt,
                'factor': factor,
                'o': float(c[3]),
                'h': float(c[4]),
                'l': float(c[5]),
                'c': float(c[6]),
                'v': float(c[9]),
            })

    if not rows_raw:
        return []

    # 最新因子 = 最新日期（距今最近）对应的因子，不是max(factor)
    # 原因：因子大小≠日期远近，部分基金拆分导致历史因子反而大于最新因子
    latest_row = max(rows_raw, key=lambda r: r['time'])
    latest_factor = latest_row['factor']
    if latest_factor == 0:
        latest_factor = 1.0

    rows = []
    for r in rows_raw:
        f = r['factor']
        if f == 1.0:
            # factor=1.0表示价格已经是当前等效，不需要调整
            rows.append({
                'time': r['time'],
                'o': round(r['o'], 4),
                'h': round(r['h'], 4),
                'l': round(r['l'], 4),
                'c': round(r['c'], 4),
                'v': r['v'],
            })
        else:
            # factor < 1.0，用前复权公式
            rows.append({
                'time': r['time'],
                'o': round(r['o'] * f / latest_factor, 4),
                'h': round(r['h'] * f / latest_factor, 4),
                'l': round(r['l'] * f / latest_factor, 4),
                'c': round(r['c'] * f / latest_factor, 4),
                'v': r['v'],
            })
    return rows

def aggregate(rows, freq):
    df = pd.DataFrame(rows)
    df['time'] = pd.to_datetime(df['time'])
    df = df.set_index('time').sort_index()
    grp_freq = 'W-FRI' if freq == 'W' else 'ME'
    grp = df.groupby(pd.Grouper(freq=grp_freq))
    agg_rows = []
    for (_, sub) in grp:
        if len(sub) == 0:
            continue
        sub = sub.sort_values('time')
        open_px  = float(sub.iloc[0]['o'])
        close_px = float(sub.iloc[-1]['c'])
        agg_rows.append({
            'time': str(_)[:10],
            'o':    open_px,
            'h':    float(sub['h'].max()),
            'l':    float(sub['l'].min()),
            'c':    close_px,
            'v':    float(sub['v'].sum()),
            'pct':  float((close_px - open_px) / open_px * 100) if open_px != 0 else 0,
        })
    return agg_rows

# ─── 预计算任务 ─────────────────────────────────────────────────────────────

def task_daily(code, loader):
    try:
        rows = loader(code)
        if not rows:
            return False
        ind = compute(rows)
        out = {'rows': rows, 'indicators': ind}
        out_path = os.path.join(OUT_DIR, f'{code}.json')
        with open(out_path, 'w') as f:
            json.dump(out, f)
        return True
    except Exception as e:
        print(f'ERROR daily {code}: {e}', flush=True)
        return False

def task_weekly_monthly(code, loader):
    try:
        rows = loader(code)
        if len(rows) < 60:
            return False
        # 周K：freq='W-FRI' 周五结，算是A股官方编制
        for freq, grp_freq in [('W','W-FRI'), ('M','ME')]:
            df_tmp = pd.DataFrame(rows)
            df_tmp['time'] = pd.to_datetime(df_tmp['time'])
            df_tmp = df_tmp.set_index('time').sort_index()
            grp = df_tmp.groupby(pd.Grouper(freq=grp_freq))
            agg_rows = []
            for (name, sub) in grp:
                if len(sub) == 0:
                    continue
                sub = sub.sort_values('time')
                open_px  = float(sub.iloc[0]['o'])
                close_px = float(sub.iloc[-1]['c'])
                agg_rows.append({
                    'time': str(name)[:10],
                    'o':    open_px,
                    'h':    float(sub['h'].max()),
                    'l':    float(sub['l'].min()),
                    'c':    close_px,
                    'v':    float(sub['v'].sum()),
                    'pct':  float((close_px - open_px) / open_px * 100) if open_px != 0 else 0,
                })
            if len(agg_rows) < 20:
                continue
            ind = compute(agg_rows)
            out = {
                'period': freq,
                'times':  [r['time'] for r in agg_rows],
                'rows':   [{'time':r['time'],'o':r['o'],'h':r['h'],'l':r['l'],
                            'c':r['c'],'v':r['v'],'pct':r['pct']} for r in agg_rows],
                'indicators': ind,
            }
            out_path = os.path.join(OUT_DIR, f'{code}_{freq.lower()}.json')
            with open(out_path, 'w') as f:
                json.dump(out, f, ensure_ascii=False)
        return True
    except Exception as e:
        print(f'ERROR wm {code}: {e}', flush=True)
        return False

def collect_selected_codes():
    """从 today/result_*.txt 读取所有已选股代码"""
    codes = set()
    for f in glob.glob(os.path.join(TODAY_DIR, 'result_*.txt')):
        with open(f) as fp:
            for line in fp:
                line = line.strip()
                if re.match(r'^\d{6}\.(?:SZ|SH|BJ)$', line):
                    codes.add(line)
    return sorted(codes)

def run(source, mode, codes=None):
    global OUT_DIR
    OUT_DIR = os.path.join(TODAY_DIR, 'indicators_etf' if source == 'etf' else 'indicators')
    if codes is None:
        # 全量模式：从目录加载所有CSV
        if source == 'stock':
            data_dir = DATA_DIR_STOCK
            loader = load_csv_stock
        else:
            data_dir = DATA_DIR_ETF
            loader = load_csv_etf
        files = glob.glob(os.path.join(data_dir, '*.csv'))
        codes = [os.path.basename(f).replace('.csv', '') for f in files]

    print(f'[{source}] 预计算 {len(codes)} 个，输出到 {OUT_DIR}')

    if source == 'stock':
        loader = load_csv_stock
    else:
        loader = load_csv_etf

    done = 0
    with concurrent.futures.ProcessPoolExecutor(max_workers=8) as ex:
        if mode in ('daily', 'all'):
            futs = {ex.submit(task_daily, code, loader): code for code in codes}
            for fut in concurrent.futures.as_completed(futs):
                if fut.result():
                    done += 1
                if done % 50 == 0 and done > 0:
                    print(f'已完成 {done}/{len(codes)}', flush=True)

        if mode in ('weekly', 'all'):
            futs = {ex.submit(task_weekly_monthly, code, loader): code for code in codes}
            for fut in concurrent.futures.as_completed(futs):
                if fut.result():
                    done += 1
                if done % 50 == 0 and done > 0:
                    print(f'已完成 {done}/{len(codes)}', flush=True)

    print(f'[{source}] 完成！')

# ─── 入口 ───────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='预计算K线指标')
    parser.add_argument('--mode', choices=['daily','weekly','all'], default='all')
    parser.add_argument('--source', choices=['stock','etf','all'], default='all')
    parser.add_argument('--from-results', action='store_true',
                        help='从today/result_*.txt读取已选股代码，只预计算这些')
    parser.add_argument('--etf', action='store_true',
                        help='同时处理ETF（用于ETF页面预加载）')
    args = parser.parse_args()

    if args.from_results:
        codes = collect_selected_codes()
        print(f'从选股结果读取到 {len(codes)} 个股票代码')
        run('stock', args.mode, codes=codes)
        if args.etf:
            # ETF暂时还是全量（ETF没有战法筛选）
            run('etf', args.mode)
    else:
        if args.source in ('stock', 'all'):
            run('stock', args.mode)
        if args.source in ('etf', 'all'):
            run('etf', args.mode)