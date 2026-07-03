# Stock K线量化选股系统

> 张总私人股票量化分析平台 · 每日 17:00 自动运行 · **当前版本 v5.0**

---

## 功能概览

| 模块 | 说明 |
|------|------|
| **7大选股战法** | 补票龙 / TePu龙 / 填坑龙 / 大波浪龙 / 红悬停龙 / 蓄力龙 / 高业绩龙（财务） |
| **每日选股** | Tushare全市场日线数据 → 7大策略选股 → K线图生成 → HTML发布 |
| **微盘温度计** | 全市场微盘股1000成分股估值分位 + 多指标拥挤度监测 |
| **行情监控** | 抱团拥挤度折线图（2024至今）+ 市场温度雷达 |
| **ETF数据管道** | Tushare+akshare+Sina多源下载 → 预计算indicators → 扁平化列表展示 |
| **K线图展示** | 日式阳红阴绿、7条均线、成交量、缩放/拖动/双击放大 |
| **每日A股总结** | 行业温度 / 市场温度 / 风险提示推送 |
| **财务分析** | Tushare财报 → 季度同比筛选 → 高成长股独立展示 |

---

## 目录结构

```
stock/
├── README.md
├── requirements.txt           # Python依赖
├── .gitignore                 # 忽略运行时产物 (daily_result/、data/weipan_*、debug页等)
│
├── deploy/                    # 部署配置
│   ├── nginx_stock.conf       # nginx站点配置 (8080端口, 119.28.106.127)
│   └── README.md              # 部署说明
│
├── data/                      # 数据目录 (运行时产物，不入库)
│   ├── kline/                 # A股日线数据 (Tushare)
│   ├── etf/                   # ETF日线数据 (akshare+Sina)
│   ├── financial/             # 财务数据 (Tushare)
│   ├── market_crowding.csv    # 抱团拥挤度指标
│   ├── weipan_metrics.csv     # 微盘温度计多指标
│   ├── weipan_imgs/           # 微盘温度计图表
│   └── weipan_raw/            # 微盘原始数据
│
├── daily_result/              # 每日选股结果 (不入库)
│   ├── today/                 # 当日最新结果 (固定链接)
│   ├── {YYYYMMDD}/            # 历史归档
│   └── dates.json             # 历史日期索引
│
├── frontend/                  # 前端页面
│   ├── index.html             # 选股结果总览页
│   ├── stock.html             # K线图详情页
│   ├── market.html            # 抱团拥挤度图表页
│   ├── market_summary.html    # 每日A股市场总结
│   ├── etf.html               # ETF列表页
│   ├── weipan.html            # 微盘温度计主页
│   ├── weipan_images.html     # 微盘温度计图表集
│   └── assets/                # 静态资源 (CSS/JS/图表库)
│
├── scripts/                   # 定时任务脚本
│   └── stock_daily_job.sh     # 每日17:00 cron实际调用
│
└── src/                       # 核心源码
    ├── data_fetch/            # 数据获取
    │   ├── get_data.py        # A股日线 (Tushare)
    │   ├── get_etf.py         # ETF数据 (akshare+Sina+Tushare)
    │   └── get_financial.py   # 财务数据 (Tushare)
    │
    ├── strategies/             # 7大选股战法 (参数硬编码)
    │   ├── analyze_bukou.py   # 补票龙
    │   ├── analyze_tepuse.py  # TePu龙
    │   ├── analyze_tiankeng.py# 填坑龙
    │   ├── analyze_dabolang.py# 大波浪龙
    │   ├── analyze_redhover.py# 红悬停龙
    │   ├── analyze_xulilong.py# 蓄力龙
    │   └── analyze_financial.py# 高业绩龙
    │
    ├── generators/             # 生成器
    │   ├── precompute.py       # ETF指标预计算
    │   ├── gen_notification.py # 微信通知生成
    │   ├── gen_html.py         # K线HTML生成
    │   ├── gen_index.py        # 首页HTML生成
    │   ├── gen_etf_klines.py   # ETF K线数据生成
    │   ├── gen_weipan.py        # 微盘温度计生成器
    │   ├── gen_weipan_jq.py     # 微盘JQ算法对齐版
    │   ├── gen_weipan_phase0.py # 微盘Phase0: 数据下载
    │   ├── gen_weipan_phase1.py # 微盘Phase1: 指标计算
    │   └── gen_weipan_images.py # 微盘图表生成
    │
    └── utils/                  # 工具
        ├── log_config.py       # 日志配置 (统一接入)
        ├── check_trading_day.py
        └── get_prev_trade_date.py
```

---

## 每日任务流程 (17:00)

```
1. 数据下载
   ├── get_data.py             # Tushare全市场日线 (~120min, 500次/min限速)
   ├── get_etf.py              # ETF数据 (Tushare主源 + akshare+Sina备用)
   └── get_financial.py        # 财报数据

2. 战法选股 (7大战法并行)
   ├── analyze_bukou.py        # 补票龙
   ├── analyze_tepuse.py       # TePu龙
   ├── analyze_tiankeng.py     # 填坑龙
   ├── analyze_dabolang.py     # 大波浪龙
   ├── analyze_redhover.py     # 红悬停龙
   ├── analyze_xulilong.py     # 蓄力龙
   └── analyze_financial.py    # 高业绩龙(财务)

3. 微盘温度计
   ├── gen_weipan_phase0.py    # Phase0: 下载微盘原始数据
   ├── gen_weipan_phase1.py    # Phase1: 计算多指标
   ├── gen_weipan.py           # 整合生成
   └── gen_weipan_images.py    # 渲染图表

4. 行情监控 + 每日总结
   ├── 抱团拥挤度图表生成 (market.html)
   └── 每日A股市场总结 (market_summary.html)

5. 结果通知
   └── gen_notification.py → stock_daily_result.txt → openclaw微信

6. K线图生成
   └── gen_html.py            # 为入选股票生成K线HTML

7. HTML发布
   ├── 归档: today/ → {YYYYMMDD}/
   └── 生成: /daily_result/today/index.html
```

**访问地址**: `http://119.28.106.127:8080/`（自动跳转到 `stock.html?date=today`）

---

## 7大选股战法

### 补票龙 (BBIShortLongSelector)
- 条件: BBI多空头排列，回踩BBI买入

### TePu龙 (BreakoutVolumeKDJSelector)
- 条件: 放量突破 + KDJ金叉

### 填坑龙 (PeakKDJSelector)
- 条件: 历史高点 + KDJ择时

### 大波浪龙 (BigWaveSelector)
- 条件: 月线多头(3月↑) + 周线多头(6周↑) + 日线回踩M5/M10

### 红悬停龙 (RedHoverSelector)
- 条件: 阳线放量上影线，悬停形态

### 蓄力龙 (XuliLongSelector)
- 条件: 长时间缩量横盘后放量启动

### 高业绩龙 (FinancialGrowthSelector)
- 条件: 财报同比营收/净利增长 + 季度环比改善

---

## 微盘温度计

### 数据源
- 成分股池：JQ原始1000只微盘股（Tushare daily_basic + fina_indicator 重建）
- 采样频率：每5个交易日一个采样点（避免日历月末噪声）
- 数据范围：20171228至今

### 核心指标
- 估值分位（近3年滚动 percentile）
- 换手率拥挤度
- 归母净利润同比增速
- 综合温度 score（rolling median 平滑 window=3）

### 算法对齐
严格对齐 JQ `weipanweiduji.py` 原始逻辑，禁止自行简化。完整两阶段模式：
- Phase0 全量数据下载到本地（避免 API 重复调用）
- Phase1 本地计算全部指标

---

## ETF数据管道

### 数据源
- **主源**: Tushare (`fund_daily` + `fund_adj`)
- **备用**: akshare → Sina (`fund_etf_hist_sina`)
- **黑名单**: 2394只问题ETF写入 `data/etf_blacklist.txt`，三处生效

### 筛选流程
```
全部ETF下载 (~2560只)
    ↓
过滤黑名单 (2394只)
    ↓
按benchmark分组 → 组内成交额最大
    ↓
约382只ETF入选
```

### 前复权公式
```
前复权价格 = 原始价格 × 当日因子 ÷ 最新因子
```

---

## K线图标准

| 项目 | 标准 |
|------|------|
| 颜色 | 日式阳红阴绿 |
| 红K | 空心阳线 |
| 均线 | 7条 (MA5/10/20/30/60/120/240)，细线 |
| 比例 | 30:20 |
| K线数 | 450日 |
| DPI | 150 |
| 压缩 | pngquant |
| **ETF同标准** | |

### 页面交互
- 战略卡片 → 弹窗K线图
- 双指/滚轮缩放、鼠标拖动
- 双击2x放大
- 边界限制不滑出屏幕
- 日K / 周K / 月K 三Tab切换
- ◀ ▶ 战法内股票切换

---

## nginx部署

项目自带 `deploy/nginx_stock.conf`，监听 8080 端口，对应 `http://119.28.106.127:8080/`。

部署方式详见 `deploy/README.md`。

---

## 依赖

```
akshare>=1.17.7
mootdx>=0.11.7
pandas>=2.3.0
tqdm>=4.66.4
tushare>=1.4.29
scipy>=1.14.1
```

---

## 版本历史

- **v5.0** (2026-07-03) 最终可发布版：nginx配置归档到 `deploy/`、daily_result 完全不入库、微盘温度计全套上线（5个生成器 + 2个前端页面）、行情监控/抱团拥挤度、每日A股总结、强化 .gitignore
- **v4.0** (2026-06) 抱团拥挤度、market.html、ETF黑名单强化、Phase0/Phase1两阶段微盘架构
- **v3.9** 微盘温度计初版（Phase0）
- **v3.8** 数据源重构（akshare + Sina双轨）
- **v3.7** 项目全面优化
- **v3.6** README编写 + GitHub推送
- **v3.5 LTS** ETF黑名单机制、K线蓄力龙修复、前复权adj_factor修复
- **v3.3** ETF扁平化列表、无分组
- **v3.1** 大波浪战法新增
- **v2.x** 早期重构版本

---

*最后更新: 2026-07-03 (v5.0 release)*