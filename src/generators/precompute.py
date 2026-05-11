#!/usr/bin/env python3
"""
预计算K线指标数据，支持三种模式：
  --mode daily   : 日线指标
  --mode weekly  : 周K+月K
  --mode all     : 三种都跑
输出统一到 daily_result/today/indicators/

支持两种数据源：
  --source stock : 从 data_kline/*.csv 读取（默认）
  --source etf   : 从 data_etf/*.csv 读取

特殊模式：
  --from-results : 从 today/result_*.txt 读取已选股代码，只预计算这些
"""
import os, json, sys, glob, argparse, concurrent.futures, re
import pandas as pd

DATA_DIR_STOCK = '/home/bange/stock/data_kline'
DATA_DIR_ETF   = '/home/bange/stock/data_etf'
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
    path = os.path.join(DATA_DIR_ETF, f'{code}.csv')
    rows = []
    with open(path) as f:
        next(f)
        for line in f:
            c = line.strip().split(',')
            if len(c) < 10: continue
            # 转换日期格式 YYYYMMDD -> YYYY-MM-DD
            d = c[1]
            date_fmt = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
            rows.append({'time': date_fmt, 'o': float(c[2]), 'h': float(c[3]),
                         'l': float(c[4]), 'c': float(c[5]), 'v': float(c[9])})
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