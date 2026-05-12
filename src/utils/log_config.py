#!/usr/bin/env python3
"""统一日志配置 - 全流程输出到同一日志文件，按步骤标签区分"""
import logging
import sys
from pathlib import Path

# 标准日志格式（带时间戳+步骤标签）
LOG_FORMAT = "%(asctime)s [%(levelname)s] [%(name)s] %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# 日志目录和统一日志文件
LOG_DIR = Path("/home/bange/stock/log")
LOG_DIR.mkdir(parents=True, exist_ok=True)
UNIFIED_LOG = LOG_DIR / "stock_daily_job.log"


def get_logger(step_name: str) -> logging.Logger:
    """获取统一日志的logger，写入 stock_daily_job.log
    
    Args:
        step_name: 操作步骤名，如"下载数据"、"分析选股"、"预计算"等
    """
    logger = logging.getLogger(step_name)
    logger.setLevel(logging.INFO)
    
    # 避免重复添加handler
    if logger.handlers:
        return logger
    
    # 文件handler（统一日志文件）
    fh = logging.FileHandler(UNIFIED_LOG, mode="a", encoding="utf-8")
    fh.setLevel(logging.INFO)
    fh.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))
    
    # 控制台handler
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))
    
    logger.addHandler(fh)
    logger.addHandler(ch)
    
    return logger
