#!/bin/bash
# 每日股票分析任务
# 位置: /home/bange/stock/scripts/stock_daily_job.sh

PROJECT_ROOT="/home/bange/stock"
SRC="$PROJECT_ROOT/src"
TODAY_DIR="$PROJECT_ROOT/daily_result/today"
export PYTHONPATH="$SRC:$PYTHONPATH"

cd "$PROJECT_ROOT"

# ========== 步骤0：判断今天是否为交易日 ==========
check_result=$(python3 "$SRC/utils/check_trading_day.py")
echo "[$(date)] 交易日检查: $check_result"
if [ "$check_result" = "NON_TRADING_DAY" ]; then
    exit 0
fi

# ========== 步骤1：归档上一交易日，创建今日目录 ==========
PREV_TRADE_DATE=$(python3 "$SRC/utils/get_prev_trade_date.py")
PREV_DIR="$PROJECT_ROOT/daily_result/$PREV_TRADE_DATE"

if [ -d "$TODAY_DIR" ] && [ "$(ls -A $TODAY_DIR 2>/dev/null)" ]; then
    mkdir -p "$PREV_DIR"
    # 归档 result_*.txt（移动）
    mv $TODAY_DIR/result_*.txt $PREV_DIR/ 2>/dev/null
    # 归档 indicators/（复制，因为生成耗时）
    if [ -d "$TODAY_DIR/indicators" ]; then
        cp -r $TODAY_DIR/indicators $PREV_DIR/
        echo "[$(date)] indicators/ 已归档到 $PREV_DIR"
    fi
    echo "[$(date)] 上一交易日已归档到 $PREV_DIR"
fi

# 清理30天前历史文件
find "$PROJECT_ROOT/daily_result/" -maxdepth 1 -type d -name "20*" -mtime +30 | while read d; do
    [ "$d" != "$TODAY_DIR" ] && rm -rf "$d" && echo "[$(date)] 清理过期: $d"
done

# 创建今日目录
mkdir -p $TODAY_DIR

# ========== 步骤2：下载数据 ==========
echo "[$(date)] 开始下载数据..."
python3 "$SRC/data_fetch/get_data.py"

# ========== 步骤3：分析选股（6个战法） ==========
echo "[$(date)] 开始补票龙..."
python3 "$SRC/strategies/analyze_bukou.py" --out-dir "$TODAY_DIR"

echo "[$(date)] 开始TePu龙..."
python3 "$SRC/strategies/analyze_tepuse.py" --out-dir "$TODAY_DIR"

echo "[$(date)] 开始填坑龙..."
python3 "$SRC/strategies/analyze_tiankeng.py" --out-dir "$TODAY_DIR"

echo "[$(date)] 开始大波浪龙..."
python3 "$SRC/strategies/analyze_dabolang.py" --out-dir "$TODAY_DIR"

echo "[$(date)] 开始红悬停龙..."
python3 "$SRC/strategies/analyze_redhover.py" --out-dir "$TODAY_DIR"

echo "[$(date)] 开始高业绩龙..."
python3 "$SRC/strategies/analyze_financial.py" --out-dir "$TODAY_DIR"

# ========== 步骤4：预计算指标（只计算已选股） ==========
echo "[$(date)] 开始预计算指标..."
python3 "$SRC/generators/precompute.py" --mode all --from-results

# ========== 步骤5：更新股票中文名表 ==========
echo "[$(date)] 更新股票中文名表..."
python3 "$SRC/generators/gen_stock_names.py"

# ========== 步骤6：下载ETF K线数据 ==========
echo "[$(date)] 下载ETF K线数据..."
python3 "$SRC/data_fetch/get_etf.py"

# ========== 步骤7：预计算ETF指标 ==========
echo "[$(date)] 预计算ETF指标（日线+周线+月线）..."
python3 "$SRC/generators/precompute.py" --source etf --mode all

# ========== 步骤8：生成ETF列表JSON ==========
echo "[$(date)] 生成ETF列表JSON..."
python3 "$SRC/generators/gen_etf_list.py"

# ========== 步骤9：生成通知文件 ==========
echo "[$(date)] 生成通知文件..."
python3 "$SRC/generators/gen_notification.py"

# ========== 步骤10：生成 dates.json ==========
echo "[$(date)] 生成 dates.json..."
python3 "$SRC/generators/gen_index.py"

echo "[$(date)] 全部完成"
