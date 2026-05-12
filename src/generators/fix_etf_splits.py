#!/usr/bin/env python3
"""
精准修复ETF前复权 - 只修复已确认发生过合并的ETF
不自动检测，基于已知事件手动修正
"""
import pandas as pd, subprocess
from pathlib import Path

ETF_DIR = Path('/home/bange/stock/data_etf')

# 已确认发生过合并/拆分的ETF：(code, 合并日期, 合并因子ratio)
# ratio = 合并后首日收盘 / 合并前一日收盘 (历史价格需乘以ratio)
CONFIRMED_SPLITS = [
    ('159516.SZ', '20260330', 0.5133),  # 2合1，adj_factor=2
    ('512760.SH', '20260327', 0.5025),  # 2合1
]

def fix_one(code, split_date, ratio):
    csv_path = ETF_DIR / f'{code}.csv'
    if not csv_path.exists():
        print(f"  [{code}] CSV不存在，跳过")
        return
    
    df = pd.read_csv(csv_path)
    df['date'] = pd.to_datetime(df['date'], format='%Y%m%d')
    df = df.sort_values('date').reset_index(drop=True)
    
    # 前复权：合并日之前的价格乘以ratio
    mask = df['date'] < split_date
    n = mask.sum()
    if n == 0:
        print(f"  [{code}] 无历史数据，跳过")
        return
    
    print(f"  [{code}] 合并日={split_date}, 因子={ratio:.4f}, 修正{n}条历史价格")
    for col in ['pre_close', 'open', 'high', 'low', 'close']:
        df.loc[mask, col] *= ratio
    df['change'] = df['close'] - df['pre_close']
    df['pct_chg'] = df['close'] / df['pre_close'] - 1
    
    df['date'] = df['date'].dt.strftime('%Y%m%d')
    df.to_csv(csv_path, index=False)

def main():
    print("精准修复ETF前复权...")
    for code, date, ratio in CONFIRMED_SPLITS:
        fix_one(code, date, ratio)
    
    print("\n重新生成指标预计算...")
    r = subprocess.run(
        ['python3', '/home/bange/stock/src/generators/precompute.py', '--source', 'etf'],
        capture_output=True, text=True, cwd='/home/bange/stock'
    )
    lines = r.stdout.strip().split('\n')
    print('\n'.join(lines[-5:]))
    print("\n完成!")

if __name__ == '__main__':
    main()