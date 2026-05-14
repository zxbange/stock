# Stock K线量化选股系统

> 张总私人股票量化分析平台 · 每日 17:00 自动运行

---

## 功能概览

| 模块 | 说明 |
|------|------|
| **7大选股战法** | 补票龙 / TePu龙 / 填坑龙 / 大波浪龙 / 红悬停龙 / 蓄力龙 / 高业绩龙（财务） |
| **每日选股** | Tushare全市场日线数据 → 7大策略选股 → K线图生成 → HTML发布 |
| **ETF数据管道** | akshare+Sina双源下载 → 预计算indicators → 扁平化列表展示 |
| **K线图展示** | 日式阳红阴绿、7条均线、成交量、缩放/拖动/双击放大 |
| **财务分析** | Tushare财报 → 季度同比筛选 → 高成长股独立展示 |

---

## 目录结构

```
stock/
├── README.md
├── requirements.txt           # Python依赖
├── configs.json               # (已废弃，各策略参数硬编码)
│
├── data/                      # 数据目录
│   ├── data_kline/            # A股日线数据 (Tushare)
│   ├── data_etf/              # ETF日线数据 (akshare+Sina)
│   ├── data_financial/         # 财务数据 (Tushare)
│   └── indicators_etf/        # ETF预计算指标
│
├── daily_result/              # 每日选股结果
│   ├── today/                 # 当日最新结果 (固定链接)
│   └── {YYYYMMDD}/            # 历史归档
│
├── frontend/                  # 前端页面
│   ├── index.html             # 选股结果总览页
│   ├── stock.html             # K线图详情页
│   ├── etf.html               # ETF列表页
│   ├── css/kline.css
│   ├── js/kline.js
│   └── assets/                # 静态资源
│
├── scripts/                   # 定时任务脚本
│   └── stock_daily_job.sh     # 每日17:00 cron实际调用
│
└── src/                       # 核心源码
    ├── data_fetch/            # 数据获取
    │   ├── get_data.py        # A股日线 (Tushare)
    │   ├── get_etf.py         # ETF数据 (akshare+Sina)
    │   └── get_financial.py    # 财务数据 (Tushare)
    │
    ├── strategies/             # 7大选股战法
    │   ├── analyze_bukou.py   # 补票龙
    │   ├── analyze_tepuse.py  # TePu龙
    │   ├── analyze_tiankeng.py# 填坑龙
    │   ├── analyze_dabolang.py# 大波浪龙
    │   ├── analyze_redhover.py# 红悬停龙
    │   ├── analyze_xulilong.py# 蓄力龙
    │   └── analyze_financial.py# 高业绩龙
    │
    ├── generators/             # 生成器
    │   ├── precompute.py      # ETF指标预计算
    │   ├── gen_notification.py# 微信通知生成
    │   ├── gen_index.py       # 首页HTML生成
    │   └── gen_etf_klines.py  # ETF K线数据生成
    │
    └── utils/                  # 工具
        ├── log_config.py      # 日志配置
        ├── check_trading_day.py
        └── get_prev_trade_date.py
```

---

## 每日任务流程 (17:00)

```
1. 数据下载
   └── get_data.py             # Tushare全市场日线 (~120min, 500次/min限速)

2. 战法选股
   ├── analyze_bukou.py        # 补票龙
   ├── analyze_tepuse.py       # TePu龙
   ├── analyze_tiankeng.py      # 填坑龙
   ├── analyze_dabolang.py      # 大波浪龙
   ├── analyze_redhover.py      # 红悬停龙
   ├── analyze_xulilong.py      # 蓄力龙
   └── analyze_financial.py     # 高业绩龙(财务)

3. 结果通知
   └── 生成 stock_daily_result.txt → openclaw微信通知

4. K线图生成
   └── generate_kline.py       # 为入选股票生成K线PNG

5. HTML发布
   ├── 归档: today/ → {YYYYMMDD}/
   └── 生成: /daily_result/today/index.html
```

**访问地址**: `http://119.28.106.127:8080/today/` (固定链接，每日自动更新)

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

## ETF数据管道

### 数据源
- **主源**: Tushare (`fund_daily` + `fund_adj`)
- **备用**: Sina (`fund_etf_hist_sina`)
- **黑名单**: 166只问题ETF写入 `etf_blacklist.txt`，三处生效

### 筛选流程
```
全部ETF下载 (2560只)
    ↓
过滤黑名单 (166只)
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

## 依赖

```
akshare==1.17.7
mootdx==0.11.7
pandas==2.3.0
tqdm==4.66.4
tushare==1.4.29
scipy==1.14.1
```

---

## 版本历史

- **v3.5 LTS** (2026-05-13) ETF黑名单机制、K线蓄力龙修复、前复权adj_factor修复
- **v3.3** ETF扁平化列表、无分组
- **v3.1** 大波浪战法新增
- **v2.x** 早期重构版本

---

*最后更新: 2026-05-14*
