#!/usr/bin/env python3
"""共享重试工具 - 所有网络请求统一使用"""
import time
import logging
from functools import wraps
from typing import Callable, Any, Tuple

logger = logging.getLogger(__name__)


def retry_call(
    func: Callable,
    *args,
    retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    backoff: float = 2.0,
    logger_name: str = "retry",
    **kwargs,
) -> Tuple[Any, Exception | None]:
    """
    重试装饰器/工具函数，对func进行带退避的重试。

    Args:
        func: 要调用的函数
        *args: 位置参数
        retries: 最大重试次数（3=首次+2次重试）
        base_delay: 首次重试前等待秒数
        max_delay: 最大等待秒数
        backoff: 退避倍数
        logger_name: 日志logger名

    Returns:
        (result, None) - 成功
        (None, e)     - 全部失败后返回None和最后一个异常
    """
    log = logging.getLogger(logger_name)
    last_e = None

    for attempt in range(1, retries + 1):
        try:
            result = func(*args, **kwargs)
            if attempt > 1:
                log.info("%s 第%d次成功", func.__name__, attempt)
            return result, None
        except Exception as e:
            last_e = e
            if attempt == retries:
                log.error("%s 第%d次失败（已无重试次数）: %s", func.__name__, attempt, e)
                break

            delay = min(base_delay * (backoff ** (attempt - 1)), max_delay)
            log.warning(
                "%s 第%d/%d次失败，%.1f秒后重试: %s",
                func.__name__,
                attempt,
                retries,
                delay,
                e,
            )
            time.sleep(delay)

    return None, last_e


def retry_decorator(
    retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    backoff: float = 2.0,
):
    """装饰器版本：@retry_decorator(retries=3)"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            _, last_e = retry_call(
                func, *args, retries=retries,
                base_delay=base_delay, max_delay=max_delay, backoff=backoff,
                logger_name=func.__module__, **kwargs
            )
            if last_e:
                raise last_e
            return _
        return wrapper
    return decorator