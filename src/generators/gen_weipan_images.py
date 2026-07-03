#!/usr/bin/env python3
"""
微盘1000图片生成器 - 完全对齐 JoinQuant weipanweiduji.py 原始样式
"""
import sys, os
from pathlib import Path
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
from datetime import datetime

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / 'src'))
from utils.log_config import get_logger
logger = get_logger("微盘图片")

DATA_DIR = PROJECT_ROOT / 'data'
IMG_DIR = DATA_DIR / 'weipan_imgs'
IMG_DIR.mkdir(exist_ok=True)

# ─── 中文字体 ───────────────────────────────────────────────────────────────

def setup_chinese_font():
    fonts = [
        '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
        '/usr/share/fonts/truetype/wqy/wqy-microhei.ttc',
        '/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc',
    ]
    for fp in fonts:
        if os.path.exists(fp):
            logger.info("使用字体: %s", fp)
            return fp
    return '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'

FONT_PATH = setup_chinese_font()
CH_FONT = FontProperties(fname=FONT_PATH)

# ─── 全量历史分位函数（与JQ完全一致）─────────────────────────────────────────

def percentile_rank(series):
    res, values = [], []
    for v in series:
        values.append(v)
        res.append(pd.Series(values).rank(pct=True).iloc[-1])
    return pd.Series(res, index=series.index)

# ─── 数据加载 ───────────────────────────────────────────────────────────────

def load_csv():
    csv_path = DATA_DIR / 'weipan_metrics.csv'
    if not csv_path.exists():
        logger.error("CSV不存在: %s", csv_path)
        return None
    df = pd.read_csv(csv_path, dtype={'date': str})
    df['_dt'] = df['date'].apply(lambda s: datetime(int(s[:4]), int(s[4:6]), int(s[6:8])))
    df = df.dropna(subset=['_dt']).sort_values('date').reset_index(drop=True)

    # 计算所有指标的历史分位（与JQ完全一致）
    # JQ: cap_pct = percentile_rank(micro_median)
    df['cap_pct'] = percentile_rank(df['micro_median'])
    df['relative_pct'] = percentile_rank(df['relative_ratio'])
    df['crowding_pct'] = percentile_rank(df['crowding_ratio'])
    df['amount_crowding_pct'] = percentile_rank(df['amount_crowding_ratio'])

    logger.info("加载 %d 期数据（已计算分位）", len(df))
    return df

# ─── 7张图表（完全复制JQ原始样式）───────────────────────────────────────────

# JQ默认样式：白色背景，不额外设置facecolor，只设置字体
plt.rcParams.update({
    'font.sans-serif': CH_FONT.get_name(),
    'axes.unicode_minus': False,
})


def plot_cap(df, path):
    """图1：市值分位（JQ原始样式：无legend，无ylabel显式设置）"""
    fig = plt.figure(figsize=(14, 6))
    ax = fig.add_subplot(111)
    ax.plot(df['_dt'], df['cap_pct'], 'b-', linewidth=1.2)
    ax.axhline(0.8, ls='--', color='gray', alpha=0.5)
    ax.axhline(0.2, ls='--', color='gray', alpha=0.5)
    ax.set_title('微盘1000 市值分位', fontproperties=CH_FONT, fontsize=14)
    ax.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(path, dpi=150)
    plt.close()
    logger.info("图1已保存: %s", path)


def plot_relative(df, path):
    """图2：相对估值分位（叠加等权指数）"""
    fig, ax1 = plt.subplots(figsize=(14, 6))
    ax2 = ax1.twinx()

    ax1.plot(df['_dt'], df['relative_pct'], 'b-', linewidth=1.2, label='相对估值分位')
    ax2.plot(df['_dt'], df['micro_index'], 'r-', linewidth=1.2, alpha=0.75, label='最小市值1000指数')

    ax1.axhline(0.8, ls='--', color='gray', alpha=0.5)
    ax1.axhline(0.2, ls='--', color='gray', alpha=0.5)

    ax1.set_ylabel('分位值', fontproperties=CH_FONT, color='b')
    ax2.set_ylabel('指数', fontproperties=CH_FONT, color='r')

    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc='upper left', prop=CH_FONT)

    ax1.set_title('微盘1000 相对估值分位（叠加最小市值1000指数）', fontproperties=CH_FONT, fontsize=14)
    ax1.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(path, dpi=150)
    plt.close()
    logger.info("图2已保存: %s", path)


def plot_crowding(df, path):
    """图3：换手率拥挤度分位（叠加等权指数）"""
    fig, ax1 = plt.subplots(figsize=(14, 6))
    ax2 = ax1.twinx()

    ax1.plot(df['_dt'], df['crowding_pct'], 'b-', linewidth=1.2, label='换手率拥挤度分位')
    ax2.plot(df['_dt'], df['micro_index'], 'r-', linewidth=1.2, alpha=0.75, label='最小市值1000指数')

    ax1.axhline(0.8, ls='--', color='gray', alpha=0.5)
    ax1.axhline(0.2, ls='--', color='gray', alpha=0.5)

    ax1.set_ylabel('分位值', fontproperties=CH_FONT, color='b')
    ax2.set_ylabel('指数', fontproperties=CH_FONT, color='r')

    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc='upper left', prop=CH_FONT)

    ax1.set_title('微盘1000 换手率拥挤度分位（叠加最小市值1000指数）', fontproperties=CH_FONT, fontsize=14)
    ax1.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(path, dpi=150)
    plt.close()
    logger.info("图3已保存: %s", path)


def plot_amount_crowding(df, path):
    """图4：成交额拥挤度分位（叠加等权指数）"""
    fig, ax1 = plt.subplots(figsize=(14, 6))
    ax2 = ax1.twinx()

    ax1.plot(df['_dt'], df['amount_crowding_pct'], 'b-', linewidth=1.2, label='成交额拥挤度分位')
    ax2.plot(df['_dt'], df['micro_index'], 'r-', linewidth=1.2, alpha=0.75, label='最小市值1000指数')

    ax1.axhline(0.8, ls='--', color='gray', alpha=0.5)
    ax1.axhline(0.2, ls='--', color='gray', alpha=0.5)

    ax1.set_ylabel('分位值', fontproperties=CH_FONT, color='b')
    ax2.set_ylabel('指数', fontproperties=CH_FONT, color='r')

    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc='upper left', prop=CH_FONT)

    ax1.set_title('微盘1000 成交额拥挤度分位（叠加最小市值1000指数）', fontproperties=CH_FONT, fontsize=14)
    ax1.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(path, dpi=150)
    plt.close()
    logger.info("图4已保存: %s", path)


def plot_score(df, path):
    """图5：综合温度（叠加等权指数）"""
    fig, ax1 = plt.subplots(figsize=(14, 6))
    ax2 = ax1.twinx()

    ax1.plot(df['_dt'], df['score'], 'b-', linewidth=1.2, label='综合温度')
    ax2.plot(df['_dt'], df['micro_index'], 'r-', linewidth=1.2, alpha=0.75, label='最小市值1000指数')

    ax1.axhline(0.8, ls='--', color='gray', alpha=0.5)
    ax1.axhline(0.2, ls='--', color='gray', alpha=0.5)

    ax1.set_ylabel('温度', fontproperties=CH_FONT, color='b')
    ax2.set_ylabel('指数', fontproperties=CH_FONT, color='r')

    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc='upper left', prop=CH_FONT)

    ax1.set_title('微盘1000 综合温度（叠加最小市值1000指数）', fontproperties=CH_FONT, fontsize=14)
    ax1.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(path, dpi=150)
    plt.close()
    logger.info("图5已保存: %s", path)


def plot_pe_pb(df, path):
    """图6：PE/PB中位数（双轴，原始值）"""
    fig, ax1 = plt.subplots(figsize=(14, 6))
    ax2 = ax1.twinx()

    ax1.plot(df['_dt'], df['pe_median'], 'b-', linewidth=1.2, label='PE中位数')
    ax2.plot(df['_dt'], df['pb_median'], 'coral', linewidth=1.2, label='PB中位数')

    ax1.set_ylabel('PE', fontproperties=CH_FONT, color='b')
    ax2.set_ylabel('PB', fontproperties=CH_FONT, color='coral')

    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc='upper left', prop=CH_FONT)

    ax1.set_title('微盘1000 PE/PB 中位数', fontproperties=CH_FONT, fontsize=14)
    ax1.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(path, dpi=150)
    plt.close()
    logger.info("图6已保存: %s", path)


def plot_np_growth(df, path):
    """图7：归母净利润增速中位数（原始值，无legend）"""
    fig = plt.figure(figsize=(14, 6))
    ax = fig.add_subplot(111)

    valid = df[df['avg_np_growth'].notna()].copy()
    ax.plot(valid['_dt'], valid['avg_np_growth'], 'g-', linewidth=1.2)
    ax.axhline(0, ls='--', color='gray', alpha=0.5)

    ax.set_title('微盘1000 归母净利润同比增速中位数（%）', fontproperties=CH_FONT, fontsize=14)
    ax.set_ylabel('YoY %', fontproperties=CH_FONT)
    ax.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(path, dpi=150)
    plt.close()
    logger.info("图7已保存: %s", path)


# ─── 主函数 ─────────────────────────────────────────────────────────────────

def generate_all_images():
    df = load_csv()
    if df is None:
        return

    for f in IMG_DIR.glob('weipan_*.png'):
        f.unlink()

    plot_cap(df, IMG_DIR / 'weipan_1_cap.png')
    plot_relative(df, IMG_DIR / 'weipan_2_relative.png')
    plot_crowding(df, IMG_DIR / 'weipan_3_crowding.png')
    plot_amount_crowding(df, IMG_DIR / 'weipan_4_amount_crowding.png')
    plot_score(df, IMG_DIR / 'weipan_5_score.png')
    plot_pe_pb(df, IMG_DIR / 'weipan_6_pe_pb.png')
    plot_np_growth(df, IMG_DIR / 'weipan_7_np_growth.png')

    logger.info("全部7张图片生成完成")


if __name__ == '__main__':
    generate_all_images()