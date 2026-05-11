#!/usr/bin/env python3
"""判断今天是否为交易日"""
import tushare as ts
from datetime import date

ts.set_token("34ffa547652d6ddcc3b8ace33adb97f6f582656a02599a059091c705")
pro = ts.pro_api()

today = date.today().strftime('%Y%m%d')
cal = pro.trade_cal(exchange='SSE', start_date=today, end_date=today)
if cal.empty or cal.iloc[0]['is_open'] != 1:
    print("NON_TRADING_DAY")
else:
    print("TRADING_DAY")
