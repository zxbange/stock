#!/usr/bin/env python3
"""获取上一交易日日期"""
import tushare as ts
from datetime import date

pro = ts.pro_api()
today = date.today().strftime('%Y%m%d')
cal = pro.trade_cal(exchange='SSE', end_date=today, limit=2)
if len(cal) >= 2:
    print(cal.iloc[-2]['cal_date'])
else:
    print(today)
