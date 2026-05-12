#!/usr/bin/env python3
"""
ETF前复权修复脚本
检测价格断层（异常涨跌>20%），对历史价格做前复权调整，然后重新跑指标预计算
"""
import pandas as pd, glob, os, subprocess
from pathlib import Path

ETF_DIR = Path('/home/bange/stock/data_etf')

def fix_etf_csv(code):
    csv_path = ETF_DIR / f'{code}.csv'
    if not csv_path.exists():
        return code, 'no_csv'
    
    df = pd.read_csv(csv_path)
    df['date'] = pd.to_datetime(df['date'], format='%Y%m%d')
    df = df.sort_values('date').reset_index(drop=True)
    df['pct'] = df['close'].pct_change()
    
    splits = []
    for i in range(1, len(df)):
        p = df.iloc[i-1]['close']
        c = df.iloc[i]['close']
        if p > 0:
            ratio = c / p
            if abs(ratio - 1) > 0.2:
                adj = ratio
                splits.append((df.iloc[i]['date'], adj))
                print(f"  [{code}] {df.iloc[i]['date'].strftime('%Y%m%d')}: 涨跌{ratio:.2%}, 调整因子={adj:.4f}")
    
    if not splits:
        return code, 'no_split', 0
    
    for split_date, adj in splits:
        mask = df['date'] < split_date
        if mask.sum() == 0:
            continue
        df.loc[mask, 'pre_close'] *= adj
        df.loc[mask, 'open'] *= adj
        df.loc[mask, 'high'] *= adj
        df.loc[mask, 'low'] *= adj
        df.loc[mask, 'close'] *= adj
        df.loc[mask, 'change'] = df.loc[mask, 'close'] - df.loc[mask, 'pre_close']
        df.loc[mask, 'pct_chg'] = df.loc[mask, 'close'] / df.loc[mask, 'pre_close'] - 1
    
    cols = ['ts_code', 'date', 'pre_close', 'open', 'high', 'low', 'close', 'change', 'pct_chg', 'volume', 'amount']
    df_out = df[cols].copy()
    df_out['date'] = df_out['date'].dt.strftime('%Y%m%d')
    df_out.to_csv(csv_path, index=False)
    
    return code, 'fixed', len(splits)

def main():
    csv_files = list(ETF_DIR.glob('[0-9]*.csv'))
    print(f"发现 {len(csv_files)} 只ETF，开始检测分割点...")
    
    fixed = []
    for csv_path in csv_files:
        code = csv_path.stem
        result = fix_etf_csv(code)
        if result[1] == 'fixed':
            fixed.append(code)
    
    print(f"\n修复完成: {len(fixed)} 只ETF存在分割，已修正CSV")
    
    print("重新生成指标预计算...")
    result = subprocess.run(
        ['python3', '/home/bange/stock/src/generators/precompute.py', '--source', 'etf'],
        capture_output=True, text=True, cwd='/home/bange/stock'
    )
    if result.returncode == 0:
        # 取最后几行
        lines = result.stdout.strip().split('\n')
        print('\n'.join(lines[-5:]))
    else:
        print('错误:', result.stderr[-300:])
    
    print("\n完成!")

if __name__ == '__main__':
    main()