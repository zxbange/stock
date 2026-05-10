#!/bin/bash
# 每日股票分析任务
# 位置: /home/bange/stock/scripts/stock_daily_job.sh

PROJECT_ROOT="/home/bange/stock"
SRC="$PROJECT_ROOT/src"
export PYTHONPATH="$SRC:$PYTHONPATH"

cd "$PROJECT_ROOT"

# ========== 步骤0：判断今天是否为交易日 ==========
check_result=$(python3 "$SRC/utils/check_trading_day.py")

echo "[$(date)] 交易日检查: $check_result"
if [ "$check_result" = "NON_TRADING_DAY" ]; then
    exit 0
fi

# ========== 步骤1：归档上一交易日的数据，创建今日目录 ==========
TODAY_DIR="$PROJECT_ROOT/daily_result/today"
PREV_TRADE_DATE=$(python3 "$SRC/utils/get_prev_trade_date.py")
PREV_DIR="$PROJECT_ROOT/daily_result/$PREV_TRADE_DATE"

# 归档：将today目录内容移动到上一交易日目录
if [ -d "$TODAY_DIR" ] && [ "$(ls -A $TODAY_DIR 2>/dev/null)" ]; then
    mkdir -p "$PREV_DIR"
    mv $TODAY_DIR/kline_*.png $PREV_DIR/ 2>/dev/null
    mv $TODAY_DIR/result_*.txt $PREV_DIR/ 2>/dev/null
    mv $TODAY_DIR/index.html $PREV_DIR/ 2>/dev/null
    echo "[$(date)] 已归档到 $PREV_DIR"
fi

# 清理30天前历史文件
find "$PROJECT_ROOT/daily_result/" -name "*.html" -mtime +30 -delete 2>/dev/null
find "$PROJECT_ROOT/daily_result/" -name "*.png" -mtime +30 -delete 2>/dev/null

# 创建今日目录
mkdir -p "$TODAY_DIR"
echo "[$(date)] 今日目录: $TODAY_DIR"

# ========== 步骤2：写入占位页（数据生成中） ==========
cp "$PROJECT_ROOT/frontend/placeholder.html" "$TODAY_DIR/index.html"
echo "[$(date)] 占位页已写入"

# 复制hammer.min.js
cp "$PROJECT_ROOT/frontend/hammer.min.js" "$TODAY_DIR/hammer.min.js" 2>/dev/null

# ========== 步骤3：下载数据 ==========
echo "[$(date)] 开始下载数据..."
python3 "$SRC/data_fetch/get_data.py"

# ========== 步骤4：分析选股（6个战法，结果写入today/result_*.txt） ==========
echo "[$(date)] 开始补票战法..."
python3 "$SRC/strategies/analyze_bukou.py" --out-dir "$TODAY_DIR"

echo "[$(date)] 开始TePu战法..."
python3 "$SRC/strategies/analyze_tepuse.py" --out-dir "$TODAY_DIR"

echo "[$(date)] 开始填坑战法..."
python3 "$SRC/strategies/analyze_tiankeng.py" --out-dir "$TODAY_DIR"

echo "[$(date)] 开始大波浪战法..."
python3 "$SRC/strategies/analyze_dabolang.py" --out-dir "$TODAY_DIR"

echo "[$(date)] 开始红悬停战法..."
python3 "$SRC/strategies/analyze_redhover.py" --out-dir "$TODAY_DIR"

echo "[$(date)] 开始业绩稳增战法..."
python3 "$SRC/strategies/analyze_financial.py" --out-dir "$TODAY_DIR"

# ========== 步骤4.5：预计算日K/周K/月K指标（只计算已选股） ==========
echo "[$(date)] 开始预计算指标（仅已选股）..."
python3 "$SRC/generators/precompute.py" --mode all --from-results --etf

# ========== 步骤5：生成通知文件 ==========
echo "[$(date)] 生成通知文件..."
python3 "$SRC/generators/gen_notification.py"

# （步骤6 PNG K线图已停用，改用动态图表，gen_klines.py 已归档）

# ========== 步骤8：生成HTML页面（覆盖占位页） ==========
echo "[$(date)] 生成HTML页面..."
python3 "$SRC/generators/gen_html.py"

echo "[$(date)] 全部完成"
