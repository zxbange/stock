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
python3 -c "
import tushare as ts, json
pro = ts.pro_api()
df = pro.stock_basic(list_status='L', fields='ts_code,name')
names = dict(zip(df['ts_code'], df['name']))
with open('$PROJECT_ROOT/frontend/stock_names.json', 'w', encoding='utf-8') as f:
    json.dump(names, f, ensure_ascii=False)
print(f'更新了 {len(names)} 只股票的中文名')"

# ═══════════════════════════════════════════════════════════════════
# ETF K线数据处理流程（重要修复记录）
#   1. get_etf.py: 必须加 adj='qfq' 参数下载（基金专用接口）
#   2. load_csv_etf 列映射（CSV格式: ts_code,date,pre_close,open,high,low,close,change,pct_chg,volume,amount）:
#        正确: o=c[3], h=c[4], l=c[5], c=c[6], v=c[9]
#        错误: o=c[2], h=c[3], l=c[4], c=c[5]  （把pre_close/open/high/low全部读错了）
#   3. 折算/拆分前复权: 用 fund_adj API 获取因子，最新因子/latest_factor 取距今最近日期对应的因子，不是max(factor)
#   4. precompute.py run() 中 OUT_DIR 按 source 动态切换（etf→indicators_etf/, stock→indicators/）
#   5. gen_etf_list.py 生成 today/etf_list.json，侧边栏按 benchmark 分组+按成交额排序
# ═══════════════════════════════════════════════════════════════════

# ========== 步骤6：下载ETF K线数据 ==========
echo "[$(date)] 下载ETF K线数据（adj='qfq'前复权）..."
python3 "$SRC/data_fetch/get_etf.py"

# ========== 步骤7：预计算ETF指标 ==========
echo "[$(date)] 预计算ETF指标（日线+周线+月线，fund_adj因子前复权）..."
python3 "$SRC/generators/precompute.py" --source etf --mode all

# ========== 步骤8：生成ETF列表JSON ==========
echo "[$(date)] 生成ETF列表JSON（benchmark分组+成交额排序）..."
python3 "$SRC/generators/gen_etf_list.py"

# ========== 步骤9：生成通知文件 ==========
echo "[$(date)] 生成通知文件..."
python3 "$SRC/generators/gen_notification.py"

# ========== 步骤10：生成 dates.json（供入口页 fetch） ==========
echo "[$(date)] 生成 dates.json..."
python3 "$SRC/generators/gen_index.py"

echo "[$(date)] 全部完成"