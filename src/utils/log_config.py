#!/usr/bin/env python3
"""统一日志配置 - 所有脚本调用此模块获得标准化日志"""
import logging
import sys
from pathlib import Path

# 标准日志格式（带时间戳）
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# 日志目录
LOG_DIR = Path("/home/bange/stock/log")
LOG_DIR.mkdir(parents=True, exist_ok=True)


def get_logger(name: str, log_file: str = None) -> logging.Logger:
    """获取带标准格式的logger，写入对应log文件
    
    Args:
        name: logger名（一般用脚本名）
        log_file: 日志文件名，默认用 name + .log
    """
    if log_file is None:
        log_file = f"{name}.log"
    
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    
    # 避免重复添加handler
    if logger.handlers:
        return logger
    
    # 文件handler
    fh = logging.FileHandler(LOG_DIR / log_file, mode="a", encoding="utf-8")
    fh.setLevel(logging.INFO)
    fh.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))
    
    # 控制台handler
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))
    
    logger.addHandler(fh)
    logger.addHandler(ch)
    
    return logger