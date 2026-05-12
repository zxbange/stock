#!/usr/bin/env python3
"""
财务选股：同时满足年报+Q1+Q2+Q3 同比连续2年增速≥25%，净利润+EPS同时满足，最新一期必须为正
支持 --out-dir 参数，将股票代码列表输出到 result_高业绩.txt
"""

from __future__ import annotations

import argparse
import glob
import logging
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("log/financial_filter.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("financial_filter")

DATA_DIR = PROJECT_ROOT / "data/financial"
MIN_GROWTH_RATE = 0.22


def growth_rate(prev, curr):
    if prev is None or pd.isna(prev) or prev == 0:
        return None
    return (curr - prev) / abs(prev)


def period_key(end_date: str):
    if end_date.endswith('1231'):
        return 'annual'
    elif end_date.endswith('0331'):
        return 'Q1'
    elif end_date.endswith('0630'):
        return 'Q2'
    elif end_date.endswith('0930'):
        return 'Q3'
    return None


def check_stock(code: str) -> dict | None:
    """
    检查单支股票是否同时满足年报/Q1/Q2/Q3四个报表类型的筛选条件
    """
    fp = DATA_DIR / f"{code}.csv"
    if not fp.exists():
        return None

    try:
        df = pd.read_csv(fp)
        if df is None or df.empty:
            return None

        df = df.copy()
        df['end_date'] = df['end_date'].astype(str)
        df = df.sort_values('end_date')

        if 'n_income' not in df.columns or 'basic_eps' not in df.columns:
            return None

        groups = defaultdict(list)
        for _, row in df.iterrows():
            pkey = period_key(row['end_date'])
            if pkey is None:
                continue
            groups[pkey].append({
                'end_date': row['end_date'],
                'np': row['n_income'],
                'eps': row['basic_eps'],
            })

        required = {'annual', 'Q1', 'Q2', 'Q3'}
        results = {}

        for pkey in required:
            records = groups.get(pkey, [])
            if len(records) < 3:
                return None  # 缺少任何一种报表，直接淘汰

            np_vals = [r['np'] for r in records]
            eps_vals = [r['eps'] for r in records]
            dates = [r['end_date'] for r in records]

            # 取最后3条（从旧到新）
            np3 = np_vals[-3:]
            eps3 = eps_vals[-3:]
            d3 = dates[-3:]

            # 最近一期（年报/Q1/Q2/Q3各自最新一期）净利润和EPS必须为正
            if np3[-1] <= 0 or eps3[-1] <= 0:
                return None

            r1_np = growth_rate(np3[0], np3[1])
            r2_np = growth_rate(np3[1], np3[2])
            r1_eps = growth_rate(eps3[0], eps3[1])
            r2_eps = growth_rate(eps3[1], eps3[2])

            if r1_np is None or r2_np is None or r1_eps is None or r2_eps is None:
                return None

            if not (r1_np >= MIN_GROWTH_RATE and r2_np >= MIN_GROWTH_RATE and
                    r1_eps >= MIN_GROWTH_RATE and r2_eps >= MIN_GROWTH_RATE):
                return None

            results[pkey] = {
                'dates': d3,
                'net_profit': [round(x, 2) for x in np3],
                'eps': [round(x, 4) for x in eps3],
                'np_rates': [round(r1_np * 100, 2), round(r2_np * 100, 2)],
                'eps_rates': [round(r1_eps * 100, 2), round(r2_eps * 100, 2)],
            }

        return results

    except Exception as e:
        logger.warning("读取 %s 失败: %s", code, e)
    return None


def main(out_dir: Path | None = None):
    csv_files = glob.glob(str(DATA_DIR / "*.csv"))
    logger.info("共找到 %d 支股票的财务数据文件", len(csv_files))

    results = []
    for fp in csv_files:
        code = Path(fp).stem
        r = check_stock(code)
        if r:
            results.append((code, r))
            logger.info("✓ %s 年报:%s/%s/%s Q1:%s Q2:%s Q3:%s",
                       code,
                       r['annual']['dates'][0], r['annual']['dates'][1], r['annual']['dates'][2],
                       r['Q1']['dates'][1], r['Q2']['dates'][1], r['Q3']['dates'][1])

    if not results:
        logger.info("没有找到符合条件的股票")
        return []

    results.sort(key=lambda x: x[1]['annual']['np_rates'][-1], reverse=True)

    logger.info("=" * 60)
    logger.info("筛选结果：共 %d 支股票同时满足年报+Q1+Q2+Q3 连续2年增速均≥25%%", len(results))

    # 输出股票代码到 result_高业绩.txt
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
        result_txt = out_dir / "result_高业绩.txt"
        with open(result_txt, 'w', encoding='utf-8') as f:
            for code, _ in results:
                f.write(code + '\n')
        logger.info("股票列表已保存: %s", result_txt)

    output_file = "/tmp/stock_notifications/financial_filter_result.txt"
    Path(output_file).parent.mkdir(parents=True, exist_ok=True)

    period_names = {'annual': '年报', 'Q1': '一季报', 'Q2': '半年报', 'Q3': '三季报'}

    lines = [f"📈 **财务高成长筛选结果**\n"]
    lines.append(f"条件：年报+Q1+Q2+Q3 同比连续2年增速≥25%（净利润 & EPS）\n")
    lines.append(f"最新一期净利润和EPS必须为正\n")
    lines.append(f"共 **{len(results)}** 支股票符合条件\n\n")

    for code, periods in results:
        lines.append(f"**{code}**")
        for pkey in ['annual', 'Q1', 'Q2', 'Q3']:
            r = periods[pkey]
            pname = period_names[pkey]
            lines.append(f"  [{pname}] {r['dates'][0]}/{r['dates'][1]}/{r['dates'][2]}")
            lines.append(
                f"    净利润: {r['net_profit'][0]:.2f} → {r['net_profit'][1]:.2f} → {r['net_profit'][2]:.2f}"
                f" (↑{r['np_rates'][0]:.1f}% / ↑{r['np_rates'][1]:.1f}%)"
            )
            lines.append(
                f"    EPS:    {r['eps'][0]:.4f} → {r['eps'][1]:.4f} → {r['eps'][2]:.4f}"
                f" (↑{r['eps_rates'][0]:.1f}% / ↑{r['eps_rates'][1]:.1f}%)"
            )
        lines.append("")

    with open(output_file, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    logger.info("结果已保存到: %s", output_file)
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--out-dir', type=Path, default=None)
    args = parser.parse_args()
    results = main(out_dir=args.out_dir)
    if results:
        print(f"\n符合条件: {len(results)} 支")
    else:
        print("\n没有找到符合条件的股票")
