#!/usr/bin/env python3
"""Ubuntu / systemd 股票通知程序；需要 mysql-connector-python >= 9.2。"""

import logging
import fcntl
import os
import re
import signal
import sys
import time
from decimal import Decimal

import mysql.connector
import requests


CONFIG = {
    "telegram_bot_token": "8803131343:AAGNIQUtFs5EhCxucMq7ez790NKbktMzMG4",
    "telegram_chat_id": "8612207166",
    "db_host": "douguastock.mysql.rds.aliyuncs.com",
    "db_port": 3306,
    "db_user": "gt888zx_4412",
    "db_password": "gt888zx_4412",
    "db_name": "gt888zx_4412",
    "db_table": "stocks1",
    "poll_seconds": 2,
    "log_level": "INFO",
    "heartbeat_seconds": 60,
    "lock_file": "/tmp/stock-telegram-notify.lock",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("stock-notify")


def load_config():
    config = {
        key: os.getenv(key.upper(), str(value))
        for key, value in CONFIG.items()
    }
    for key, value in config.items():
        if not value or value.startswith("请填写"):
            raise ValueError(f"请填写配置：{key}")
    config["db_port"] = int(config["db_port"])
    config["poll_seconds"] = float(config["poll_seconds"])
    config["heartbeat_seconds"] = float(config["heartbeat_seconds"])
    config["log_level"] = config["log_level"].upper()
    if config["log_level"] not in ("DEBUG", "INFO", "WARNING", "ERROR"):
        raise ValueError("log_level 必须是 DEBUG、INFO、WARNING 或 ERROR")
    if config["heartbeat_seconds"] <= 0:
        raise ValueError("heartbeat_seconds 必须大于 0")
    if config["poll_seconds"] <= 0:
        raise ValueError("poll_seconds 必须大于 0")
    if not re.fullmatch(r"[A-Za-z0-9_]+", config["db_table"]):
        raise ValueError("db_table 只能包含字母、数字、下划线")
    return config


class SingleInstance:
    def __init__(self, path):
        self.path = path
        self.handle = None

    def __enter__(self):
        descriptor = os.open(self.path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        self.handle = os.fdopen(descriptor, "r+")
        try:
            fcntl.flock(self.handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.handle.close()
            raise RuntimeError("已有通知实例运行，本次退出；请勿同时手动启动和启动服务") from None
        self.handle.seek(0)
        self.handle.truncate()
        self.handle.write(str(os.getpid()))
        self.handle.flush()
        return self

    def __exit__(self, *args):
        self.handle.close()


def safe_error(error, config):
    message = str(error)
    for key in ("telegram_bot_token", "db_password"):
        secret = config[key]
        if secret:
            message = message.replace(secret, "[已隐藏]")
    return f"{type(error).__name__}: {message}"


def format_record(row):
    action = str(row["action"]).strip().upper()
    if action not in ("BUY", "SELL"):
        raise ValueError(f"记录 id={row['id']} 的 action 无效")
    amount = row["amt"]
    if isinstance(amount, Decimal):
        amount = format(amount, "f")
    return (
        f"交易时间：{row['time']}\n"
        f"股票：{row['code']}\n"
        f"操作：{'买入' if action == 'BUY' else '卖出'}\n"
        f"数量：{amount} 股"
    )


def build_batches(rows):
    batches = []
    texts, identifiers = [], []
    length = 0
    for row in rows:
        text = format_record(row)
        units = len(text.encode("utf-16-le")) // 2
        if units > 3500:
            raise ValueError(f"记录 id={row['id']} 内容过长")
        if texts and length + 2 + units > 3500:
            batches.append(("\n\n".join(texts), identifiers))
            texts, identifiers, length = [], [], 0
        length += units + (2 if texts else 0)
        texts.append(text)
        identifiers.append(row["id"])
    if texts:
        batches.append(("\n\n".join(texts), identifiers))
    return batches


class Database:
    def __init__(self, config):
        self.config = config
        self.connection = None

    def close(self):
        connection, self.connection = self.connection, None
        if connection is not None:
            try:
                connection.close()
            except Exception as error:
                logger.warning("关闭数据库连接失败：%s", safe_error(error, self.config))

    def get_connection(self):
        if self.connection is not None:
            try:
                self.connection.ping(reconnect=False)
                logger.debug("复用数据库连接 ID=%s", self.connection.connection_id)
                return self.connection
            except mysql.connector.Error as error:
                logger.warning("连接检查失败，将重建连接：%s", safe_error(error, self.config))
                self.close()
        config = self.config
        logger.info("创建数据库长连接")
        self.connection = mysql.connector.connect(
            host=config["db_host"], port=config["db_port"],
            user=config["db_user"], password=config["db_password"],
            database=config["db_name"],
            connection_timeout=10, read_timeout=20, write_timeout=20,
            autocommit=True,
        )
        try:
            with self.connection.cursor() as cursor:
                cursor.execute("SET SESSION innodb_lock_wait_timeout = 10")
        except Exception:
            self.close()
            raise
        return self.connection


def process_once(config, cycle, database, session):
    cursor = None
    stage = "初始化"
    started = time.monotonic()

    def step(name):
        nonlocal stage
        stage = name
        logger.debug("轮次=%s 步骤=%s", cycle, name)

    try:
        step("1 检查并获取数据库长连接")
        connection = database.get_connection()
        cursor = connection.cursor(dictionary=True)
        step("2 连接成功，检查实际数据库")
        cursor.execute("SELECT DATABASE() AS db, CONNECTION_ID() AS connection_id")
        identity = cursor.fetchone()
        logger.debug("实际数据库=%s 表=%s 连接ID=%s", identity["db"],
                    config["db_table"], identity["connection_id"])
        step("3 开始查询全部 NO 记录")
        cursor.execute(
            f"SELECT id, `time`, action, code, amt FROM `{config['db_table']}` "
            "WHERE isconsum = %s ORDER BY id", ("NO",),
        )
        rows = cursor.fetchall()
        logger.debug("查询完成，待发送=%s 条", len(rows))
        if not rows:
            return
        logger.info("查询到 %s 条待发送记录", len(rows))
        step("4 构建批量消息")
        batches = build_batches(rows)
        logger.info("共生成 %s 批消息", len(batches))
        for index, (message, identifiers) in enumerate(batches, start=1):
            step(f"5 发送 Telegram，批次={index}/{len(batches)} 条数={len(identifiers)}")
            response = session.post(
                f"https://api.telegram.org/bot{config['telegram_bot_token']}/sendMessage",
                json={"chat_id": config["telegram_chat_id"], "text": message},
                timeout=(10, 20),
            )
            logger.info("Telegram HTTP 状态=%s", response.status_code)
            try:
                payload = response.json()
            except ValueError:
                raise RuntimeError("Telegram 返回非 JSON 响应") from None
            finally:
                response.close()
            if not response.ok or payload.get("ok") is not True:
                raise RuntimeError(
                    f"Telegram 错误={payload.get('error_code')} "
                    f"说明={payload.get('description')} "
                    f"参数={payload.get('parameters')}"
                )
            logger.info("Telegram 接受成功，message_id=%s",
                        payload.get("result", {}).get("message_id"))
            step("6 批量更新已发送记录（自动提交）")
            placeholders = ",".join(["%s"] * len(identifiers))
            cursor.execute(
                f"UPDATE `{config['db_table']}` SET isconsum = 'YES' "
                f"WHERE id IN ({placeholders}) AND isconsum = 'NO'",
                tuple(identifiers),
            )
            logger.info("数据库更新完成，实际更新=%s 条", cursor.rowcount)
            if cursor.rowcount != len(identifiers):
                logger.warning("更新数量与发送数量不同，请检查是否有其他程序修改 isconsum")
            logger.info("批次=%s 已发送并完成数据库标记", index)
            if index < len(batches):
                time.sleep(1.1)
    except Exception as error:
        logger.error("轮次=%s 失败步骤=%s 错误=%s", cycle, stage,
                     safe_error(error, config))
        if isinstance(error, mysql.connector.Error):
            database.close()
            logger.info("数据库异常，下一轮重新连接")
    finally:
        logger.debug("轮次=%s 步骤=7 清理游标，保留数据库长连接", cycle)
        for name, resource in (("cursor", cursor),):
            if resource is not None:
                try:
                    resource.close()
                except Exception as error:
                    logger.error("关闭 %s 失败：%s", name, safe_error(error, config))
                    database.close()
        logger.debug("轮次=%s 结束，耗时=%.2f秒", cycle, time.monotonic() - started)


def main():
    config = load_config()
    logger.setLevel(config["log_level"])
    with SingleInstance(config["lock_file"]):
        run(config)


def run(config):
    logger.info("启动 PID=%s 脚本=%s", os.getpid(), os.path.abspath(__file__))
    logger.info("目标 host=%s port=%s database=%s table=%s",
                config["db_host"], config["db_port"], config["db_name"], config["db_table"])
    logger.info("配置中的同名大写环境变量优先；每轮完成后等待 %s 秒", config["poll_seconds"])
    cycle = 0
    database = Database(config)
    session = requests.Session()
    last_heartbeat = time.monotonic()
    def stop(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)
    try:
        while True:
            cycle += 1
            process_once(config, cycle, database, session)
            if time.monotonic() - last_heartbeat >= config["heartbeat_seconds"]:
                logger.info("运行心跳：已完成 %s 轮；查询及发送结果见对应日志", cycle)
                last_heartbeat = time.monotonic()
            logger.debug("等待 %s 秒后开始下一轮", config["poll_seconds"])
            time.sleep(config["poll_seconds"])
    except KeyboardInterrupt:
        logger.info("已手动停止")
    finally:
        database.close()
        session.close()


if __name__ == "__main__":
    main()
