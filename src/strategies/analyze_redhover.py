#!/usr/bin/env python3
"""
红悬停选股分析脚本

选股逻辑：
1. T-2日（倒数第3个交易日）涨停
2. T-1日（倒数第2个交易日）：
   - 最低价 >= T-2日涨停价（不限制是否涨停）
   - 成交量 >= T-2日成交量的1.5倍
3. T日（最后交易日）：
   - 未涨停
   - 最低价 >= T-2日涨停价
"""

from __future__ import annotations

import glob
import logging
import sys
from pathlib import Path

import pandas as pd

# ---------- 日志 ----------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(Path(__file__).parent.parent.parent / "log" / "redhover_filter.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("redhover_filter")

# ---------- 配置 ----------
DATA_DIR = Path(__file__).parent.parent.parent / "data_kline"

def fetch_st_stocks() -> set:
    """从Tushare实时获取ST股票列表"""
    try:
        import tushare as ts
        pro = ts.pro_api()
        df = pro.stock_basic(list_status='L', fields='ts_code,name')
        st_df = df[df['name'].str.match(r'^(\*?ST|S\*?ST|S\*?\*?ST)', na=False)]
        return set(st_df['ts_code'].tolist())
    except Exception as e:
        logging.warning("获取ST股票列表失败: %s", e)
        return set()

ST_STOCKS = fetch_st_stocks()
# 涨停阈值
LIMIT_UP_10 = 9.5    # 主板/中小板 10%涨停
LIMIT_UP_20 = 19.5   # 创业板/科创板 20%涨停
# 最小放量比例
VOLUME_RATIO = 1.5


def get_limit_rate(ts_code: str, pct_chg: float) -> float:
    """根据股票代码判断涨停阈值（10%/20%/30%）"""
    code = ts_code.upper()
    # 创业板(300/301开头) 和 科创板(688开头) 是20%涨停
    if code.startswith("300") or code.startswith("301") or code.startswith("688"):
        return 0.20
    # 北交所(9开头) 是30%涨停
    if code.startswith("9"):
        return 0.30
    return 0.10

def is_limit_up(ts_code: str, pct_chg: float) -> bool:
    """判断是否涨停（根据板块不同阈值）"""
    rate = get_limit_rate(ts_code, pct_chg)
    threshold = 9.5 if rate == 0.10 else (19.5 if rate == 0.20 else 29.5)  # 10%板块用9.5，20%用19.5，30%用29.5
    return pct_chg >= threshold


def analyze_stock(df: pd.DataFrame, fp: str) -> dict | None:
    """
    分析单支股票，返回选股结果或None
    """
    if len(df) < 3:
        return None

    row_t2 = df.iloc[-3]
    row_t1 = df.iloc[-2]
    row_t = df.iloc[-1]

    ts_code = Path(fp).stem

    # 0. 过滤ST股票
    if ts_code in ST_STOCKS:
        return None

    # 1. T-2日必须涨停
    if not is_limit_up(ts_code, row_t2["pct_chg"]):
        return None

    # 计算T-2涨停价
    pct_t2 = row_t2["pct_chg"]
    rate_t2 = get_limit_rate(ts_code, pct_t2)
    threshold_t2 = 10.0 if rate_t2 == 0.10 else 19.5
    t2_limit_price = round(row_t2["pre_close"] * (1 + rate_t2), 2)

    # 2. T-1日条件（不限是否涨停，只看低价和放量）
    if row_t1["low"] < t2_limit_price:
        return None

    # 3. T日条件（未涨停 + 低价过涨停价）
    if is_limit_up(ts_code, row_t["pct_chg"]):
        return None
    if row_t["low"] < t2_limit_price:
        return None

    return {
        "ts_code": "",  # 从文件名获取
        "date_t2": str(row_t2["date"]),
        "date_t1": str(row_t1["date"]),
        "date_t": str(row_t["date"]),
        "t2_pct": round(row_t2["pct_chg"], 2),
        "t2_limit_price": t2_limit_price,
        "t1_pct": round(row_t1["pct_chg"], 2),
        "t1_vol_ratio": round(row_t1["volume"] / row_t2["volume"], 2),
        "t1_low": row_t1["low"],
        "t_pct": round(row_t["pct_chg"], 2),
        "t_low": row_t["low"],
    }


def main():
    csv_files = glob.glob(str(DATA_DIR / "*.csv"))
    logger.info("共找到 %d 支股票数据", len(csv_files))

    results = []

    for fp in csv_files:
        try:
            df = pd.read_csv(fp, parse_dates=["date"])
            df = df.sort_values("date").reset_index(drop=True)
        except Exception as e:
            logger.warning("读取 %s 失败: %s", fp, e)
            continue

        result = analyze_stock(df, fp)
        if result:
            result["ts_code"] = Path(fp).stem  # 从文件名获取股票代码
            results.append(result)
            logger.info("✓ %s 通过筛选 T-2=%.2f%%涨停 T-1低价守住涨停价 T日未涨停 T-1放量%.2fx", 
                       result["ts_code"], result["t2_pct"], result["t1_vol_ratio"])

    logger.info("=" * 50)
    logger.info("筛选结果：共 %d 支股票符合条件", len(results))

    if results:
        results.sort(key=lambda x: x["t1_vol_ratio"], reverse=True)

        print("\n筛选出的股票：")
        print(f"{'代码':<12} {'T-2涨停':<10} {'T-1涨幅':<8} {'T-1最低':<8} {'T-1放量':<8} {'T涨幅':<8} {'T最低':<8}")
        print("-" * 70)
        for r in results:
            print(f"{r['ts_code']:<12} {r['t2_pct']:>6.2f}%  {r['t1_pct']:>6.2f}%  {r['t1_low']:>6.2f}  {r['t1_vol_ratio']:>5.2f}x  {r['t_pct']:>6.2f}%  {r['t_low']:>6.2f}")

        # 保存结果
        output_file = "/tmp/stock_notifications/redhover_result.txt"
        Path(output_file).parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(f"【红悬停选股】{results[0]['date_t']}\n")
            f.write(f"筛选条件：T-2涨停 → T-1低价≥涨停价 → T日未涨停且低价≥涨停价\n\n")
            for r in results:
                f.write(f"{r['ts_code']}\n")
            f.write(f"\n共 {len(results)} 支\n")

        logger.info("结果已保存到: %s", output_file)

        codes = [r["ts_code"] for r in results]
        return codes
    else:
        logger.info("没有找到符合条件的股票")
        return []


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="红悬停选股")
    parser.add_argument("--out-dir", help="输出目录，保存result_红悬停.txt")
    args = parser.parse_args()
    codes = main()
    if codes:
        print(f"\n符合条件的股票代码: {', '.join(codes)}")
    # 保存到指定目录
    if args.out_dir:
        out_path = Path(args.out_dir) / "result_红悬停.txt"
        with open(out_path, "w", encoding="utf-8") as f:
            f.write("红悬停战法\n")
            for code in codes:
                f.write(code + "\n")
        print(f"已保存到: {out_path}")