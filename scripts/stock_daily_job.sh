#!/bin/bash
# ============================================================
# 每日股票分析任务
# 所有输出同时记录到 log/stock_daily_job.log
# ============================================================

PROJECT_ROOT="/home/bange/stock"
SRC="$PROJECT_ROOT/src"
LOG_DIR="$PROJECT_ROOT/log"
TODAY_DIR="$PROJECT_ROOT/daily_result/today"
LOG_FILE="$LOG_DIR/stock_daily_job.log"

export PYTHONPATH="$SRC:$PYTHONPATH"
mkdir -p "$LOG_DIR"

# ---------- 日志函数 ----------
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

log_section() {
    log ""
    log "============================================================"
    log "$*"
    log "============================================================"
}

# ---------- 执行步骤函数 ----------
# $1: 步骤名称（人类可读）
# $2: 实际命令
run_step() {
    local label="$1"
    local cmd="$2"
    log ""
    log ">>> 开始 [$label]"
    log "命令: $cmd"
    local start_sec=$(date '+%s')

    set -o pipefail
    bash -c "$cmd" 2>&1 | tee -a "$LOG_FILE"
    local exit_code=$?
    local end_sec=$(date '+%s')
    local dur=$(( end_sec - start_sec ))

    if [ $exit_code -eq 0 ]; then
        log "<<< 完成 [$label]（耗时 ${dur}s）"
    else
        log "<<< 失败 [$label]，退出码=$exit_code（耗时 ${dur}s）"
    fi
    return $exit_code
}

# ============================================================
# 主流程
# ============================================================
cd "$PROJECT_ROOT"

log_section "每日股票分析任务开始 ($(date '+%Y-%m-%d %H:%M:%S'))"
log "PROJECT_ROOT=$PROJECT_ROOT"
log "PYTHONPATH=$PYTHONPATH"

# ---------- 步骤0：判断今天是否为交易日 ----------
check_result=$(python3 "$SRC/utils/check_trading_day.py")
log "交易日检查: $check_result"
if [ "$check_result" = "NON_TRADING_DAY" ]; then
    log "今天不是交易日，退出"
    exit 0
fi

# ---------- 步骤1：归档上一交易日，创建今日目录 ----------
PREV_TRADE_DATE=$(python3 "$SRC/utils/get_prev_trade_date.py")
PREV_DIR="$PROJECT_ROOT/daily_result/$PREV_TRADE_DATE"

if [ -d "$TODAY_DIR" ] && [ "$(ls -A $TODAY_DIR 2>/dev/null)" ]; then
    mkdir -p "$PREV_DIR"
    mv $TODAY_DIR/result_*.txt $PREV_DIR/ 2>/dev/null
    if [ -d "$TODAY_DIR/indicators" ]; then
        cp -r $TODAY_DIR/indicators $PREV_DIR/
        log "[归档] indicators/ -> $PREV_DIR"
    fi
    log "[归档] 上一交易日 $PREV_DIR 已创建"
fi

# 清理30天前历史
find "$PROJECT_ROOT/daily_result/" -maxdepth 1 -type d -name "20*" -mtime +30 | \
    while read d; do
        [ "$d" != "$TODAY_DIR" ] && rm -rf "$d" && log "[清理] 过期目录: $d"
    done

mkdir -p $TODAY_DIR

# ---------- 步骤2：下载K线数据 ----------
run_step "下载K线数据" "python3 $SRC/data_fetch/get_data.py"

# ---------- 步骤3：6个战法选股 ----------
for step_info in \
    "补票龙:python3 $SRC/strategies/analyze_bukou.py --out-dir $TODAY_DIR" \
    "TePu龙:python3 $SRC/strategies/analyze_tepuse.py --out-dir $TODAY_DIR" \
    "填坑龙:python3 $SRC/strategies/analyze_tiankeng.py --out-dir $TODAY_DIR" \
    "大波浪龙:python3 $SRC/strategies/analyze_dabolang.py --out-dir $TODAY_DIR" \
    "红悬停龙:python3 $SRC/strategies/analyze_redhover.py --out-dir $TODAY_DIR" \
    "高业绩龙:python3 $SRC/strategies/analyze_financial.py --out-dir $TODAY_DIR"; do
    label="${step_info%%:*}"
    cmd="${step_info#*:}"
    run_step "$label" "$cmd"
done

# ---------- 步骤4：预计算指标 ----------
run_step "预计算指标" "python3 $SRC/generators/precompute.py --mode all --from-results"

# ---------- 步骤5：更新股票中文名表 ----------
run_step "更新股票中文名表" "python3 $SRC/generators/gen_stock_names.py"

# ---------- 步骤6：下载ETF K线数据 ----------
run_step "下载ETF数据" "python3 $SRC/data_fetch/get_etf.py"

# ---------- 步骤7：预计算ETF指标 ----------
run_step "预计算ETF指标" "python3 $SRC/generators/precompute.py --source etf --mode all"

# ---------- 步骤8：生成ETF列表JSON ----------
run_step "生成ETF列表JSON" "python3 $SRC/generators/gen_etf_list.py"

# ---------- 步骤9：生成通知文件 ----------
run_step "生成通知文件" "python3 $SRC/generators/gen_notification.py"

# ---------- 步骤10：生成 dates.json ----------
run_step "生成 dates.json" "python3 $SRC/generators/gen_index.py"

log_section "每日股票分析任务全部完成 ($(date '+%Y-%m-%d %H:%M:%S'))"
