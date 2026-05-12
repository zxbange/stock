#!/usr/bin/env python3
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.log_config import get_logger
logger = get_logger("生成ETF_K线图")
"""
ETF K线图批量生成器 - 从 data_etf/*.csv 读取本地数据
纯本地计算，不走API，多进程并行
"""
import os, sys, time, shutil, glob
from pathlib import Path
from multiprocessing import Pool, cpu_count

PROJECT_ROOT = Path(__file__).parent.parent.parent
ETF_DATA_DIR = PROJECT_ROOT / "data_etf"
KLINE_OUT_DIR = ETF_DATA_DIR / "kline"
KLINE_OUT_DIR.mkdir(parents=True, exist_ok=True)

COLS = ["date", "pre_close", "open", "high", "low", "close", "volume"]

def generate_etf_chart(code, periods=450):
    """生成单只ETF的K线图"""
    csv_path = ETF_DATA_DIR / f"{code}.csv"
    out_path = KLINE_OUT_DIR / f"kline_{code}.png"
    if out_path.exists():
        return code, "skip"

    try:
        import pandas as pd
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np

        df = pd.read_csv(csv_path)
        if df.empty or len(df) < 10:
            return code, "no_data"

        # 统一列名
        df = df.rename(columns={"ts_code": "code", "amount": "turnover"})
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)

        close_full = df["close"].values
        open_full  = df["open"].values
        high_full  = df["high"].values
        low_full   = df["low"].values

        # 均线（全量计算后截取）
        ma_data = {}
        for period, color, label in [
            (5,"yellow","MA5"),(10,"orange","MA10"),(20,"cyan","MA20"),
            (30,"magenta","MA30"),(60,"lime","MA60"),
            (120,"gold","MA120"),(240,"violet","MA240"),
        ]:
            if len(df) >= period:
                ma_data[period] = pd.Series(close_full).rolling(period).mean().values

        df_plot = df.tail(periods).reset_index(drop=True)
        close = close_full[-periods:]
        open_v = open_full[-periods:]
        high  = high_full[-periods:]
        low   = low_full[-periods:]
        for p in list(ma_data.keys()):
            ma_data[p] = ma_data[p][-periods:]

        # MACD
        ema12 = pd.Series(close).ewm(span=12).mean().values
        ema26 = pd.Series(close).ewm(span=26).mean().values
        dif   = ema12 - ema26
        dea   = pd.Series(dif).ewm(span=9).mean().values
        macd  = 2 * (dif - dea)

        # KDJ
        n = 9
        low_n  = pd.Series(low).rolling(n).min().values
        high_n = pd.Series(high).rolling(n).max().values
        rsv = (close - low_n) / (high_n - low_n + 1e-9) * 100
        rsv = np.nan_to_num(rsv, nan=0.5)
        K = np.zeros_like(close)
        D = np.zeros_like(close)
        K[0], D[0] = 50, 50
        for i in range(1, len(close)):
            K[i] = 2/3 * K[i-1] + 1/3 * rsv[i]
            D[i] = 2/3 * D[i-1] + 1/3 * K[i]
        J = 3 * K - 2 * D

        matplotlib.rcParams["font.sans-serif"] = ["Noto Sans CJK JP", "DejaVu Sans"]
        matplotlib.rcParams["axes.unicode_minus"] = False

        up   = close >= open_v
        down = ~up
        x    = list(range(len(df_plot)))

        fig = plt.figure(figsize=(30, 20), facecolor="white")
        gs  = fig.add_gridspec(4, 1, height_ratios=[4, 1.2, 1.5, 1.5],
                               hspace=0.06, left=0.06, right=0.96, top=0.94, bottom=0.05)
        ax1    = fig.add_subplot(gs[0])
        ax_vol = fig.add_subplot(gs[1], sharex=ax1)
        ax_macd= fig.add_subplot(gs[2], sharex=ax1)
        ax_kdj = fig.add_subplot(gs[3], sharex=ax1)

        for ax in [ax1, ax_vol, ax_macd, ax_kdj]:
            ax.set_facecolor("white")
            ax.tick_params(colors="black", labelcolor="black")
            for spine in ["bottom","top","left","right"]:
                ax.spines[spine].set_color("#999")
            ax.grid(axis="y", color="#ccc", linewidth=0.4)

        w = 0.85
        for i in x:
            color = "red" if up[i] else "green"
            body_top = max(open_v[i], close[i])
            body_bot = min(open_v[i], close[i])
            body_h   = max(body_top - body_bot, 0.001)
            if color == "red":
                ax1.plot([i,i], [low[i], body_bot], color="red", linewidth=0.8)
                ax1.plot([i,i], [body_top, high[i]], color="red", linewidth=0.8)
                ax1.add_patch(plt.Rectangle((i-w/2, body_bot), w, body_h,
                                 facecolor="none", edgecolor="red", linewidth=0.8))
            else:
                ax1.plot([i,i], [low[i], high[i]], color="green", linewidth=0.8)
                ax1.add_patch(plt.Rectangle((i-w/2, body_bot), w, body_h,
                                 facecolor="green", edgecolor="green", linewidth=0.8))

        def add_ma(p, c, lbl, lw=0.4):
            if p in ma_data:
                ax1.plot(x, ma_data[p], color=c, linewidth=lw, label=lbl)
        add_ma(5,"yellow","MA5");  add_ma(10,"orange","MA10"); add_ma(20,"cyan","MA20")
        add_ma(30,"magenta","MA30"); add_ma(60,"lime","MA60");  add_ma(120,"gold","MA120")
        add_ma(240,"violet","MA240")
        ax1.legend(loc="upper left", facecolor="#f0f0f0", labelcolor="black",
                   fontsize=8, ncol=4, framealpha=0.6)
        ax1.set_ylabel("Price", color="black", fontsize=9)
        ax1.set_title(f"ETF: {code}", color="black", fontsize=13, pad=10)

        vol = df_plot["volume"].values
        if vol.mean() > 10000:
            vol = vol / 10000
        ax_vol.bar([i for i in x if up[i]],   vol[up],   facecolor="none",       edgecolor="red",   linewidth=0.7, width=0.82)
        ax_vol.bar([i for i in x if down[i]], vol[down], facecolor="green",       edgecolor="green", linewidth=0.82)
        ax_vol.set_ylabel("Vol\n(100M)", color="black", fontsize=8)

        ax_macd.fill_between(x, macd, 0, where=(macd>=0), color="red",   alpha=0.5)
        ax_macd.fill_between(x, macd, 0, where=(macd< 0), color="green",  alpha=0.5)
        ax_macd.plot(x, dif,  color="orange", linewidth=0.8, label="DIF")
        ax_macd.plot(x, dea,  color="cyan",    linewidth=0.8, label="DEA")
        ax_macd.plot(x, macd, color="yellow",  linewidth=0.5, label="MACD")
        ax_macd.legend(loc="upper left", facecolor="#f0f0f0", labelcolor="black",
                       fontsize=7, ncol=3, framealpha=0.6)
        ax_macd.set_ylabel("MACD", color="black", fontsize=8)
        ax_macd.axhline(0, color="#888", linewidth=0.5)

        ax_kdj.plot(x, K, color="yellow", linewidth=0.9, label="K")
        ax_kdj.plot(x, D, color="orange",  linewidth=0.9, label="D")
        ax_kdj.plot(x, J, color="magenta", linewidth=0.6, label="J")
        ax_kdj.legend(loc="upper left", facecolor="#f0f0f0", labelcolor="black",
                      fontsize=7, ncol=3, framealpha=0.6)
        ax_kdj.set_ylabel("KDJ", color="black", fontsize=8)
        ax_kdj.axhline(80, color="red",   linewidth=0.4, linestyle="--", alpha=0.5)
        ax_kdj.axhline(20, color="green", linewidth=0.4, linestyle="--", alpha=0.5)

        tick_pos  = list(range(0, len(df_plot), max(1, len(df_plot)//10)))
        tick_lbls = [df_plot["date"].iloc[i].strftime("%Y-%m-%d") for i in tick_pos]
        ax_kdj.set_xticks(tick_pos)
        ax_kdj.set_xticklabels(tick_lbls, rotation=45, color="black", fontsize=7)
        ax_kdj.set_xlabel("", color="black")

        for ax in [ax1, ax_vol, ax_macd, ax_kdj]:
            ax.set_xlim(-3, len(x) + 1)

        plt.savefig(str(out_path), dpi=100, facecolor="white", edgecolor="none")
        plt.close()
        return code, "ok"

    except Exception as e:
        return code, f"err:{e}"


def main():
    csv_files = glob.glob(str(ETF_DATA_DIR / "*.csv"))
    codes = [os.path.basename(f).replace(".csv", "") for f in csv_files]
    print(f"待生成: {len(codes)} 只 ETF")

    already = len(list(KLINE_OUT_DIR.glob("kline_*.png")))
    print(f"已存在: {already} 张，跳过")

    todo = [c for c in codes if not (KLINE_OUT_DIR / f"kline_{c}.png").exists()]
    print(f"本次需生成: {len(todo)} 张")

    if not todo:
        print("全部完成")
        return

    workers = min(cpu_count(), 8)
    print(f"使用 {workers} 进程并行...")

    t0 = time.time()
    ok = skip = err = 0
    with Pool(workers) as pool:
        for code, status in pool.imap_unordered(generate_etf_chart, todo):
            if status == "ok":
                ok += 1
            elif status == "skip":
                skip += 1
            else:
                err += 1
            done = ok + skip + err
            if done % 50 == 0 or done == len(todo):
                elapsed = time.time() - t0
                rate = done / elapsed if elapsed > 0 else 0
                remaining = (len(todo) - done) / rate if rate > 0 else 0
                print(f"进度: {done}/{len(todo)}  成功:{ok}  跳过:{skip}  失败:{err}  预计剩余:{remaining:.0f}秒")

    total_time = time.time() - t0
    print(f"\n完成！共 {ok} 张，耗时 {total_time:.0f} 秒")
    print(f"图片目录: {KLINE_OUT_DIR}")


if __name__ == "__main__":
    main()
