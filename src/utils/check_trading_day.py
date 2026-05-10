#!/usr/bin/env python3
"""判断今天是否为交易日"""
import tushare as ts
from datetime import date

pro = ts.pro_api()
today = date.today().strftime('%Y%m%d')
cal = pro.trade_cal(exchange='SHE', start_date=today, end_date=today)
if cal.empty or cal.iloc[0]['is_open'] != 1:
    print("NON_TRADING_DAY")
else:
    print("TRADING_DAY")
