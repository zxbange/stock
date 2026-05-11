#!/usr/bin/env python3
"""
生成ETF K线浏览HTML（etf.html）到 today/ 目录
"""
import os, shutil
from pathlib import Path

PROJECT_ROOT = Path('/home/bange/stock')
TODAY_DIR    = PROJECT_ROOT / 'daily_result' / 'today'
FRONTEND_DIR = PROJECT_ROOT / 'frontend'

SRC_HTML   = FRONTEND_DIR / 'etf.html'
SRC_CSS    = FRONTEND_DIR / 'css' / 'kline.css'
SRC_JS     = FRONTEND_DIR / 'js' / 'etf.js'
SRC_LW     = FRONTEND_DIR / 'lightweight-charts.standalone.production.js'

DEST_DIR   = TODAY_DIR
DEST_HTML = DEST_DIR / 'etf.html'

def gen():
    # 复制前端文件到 today/
    for src, dst in [
        (SRC_HTML, DEST_DIR / 'etf.html'),
        (SRC_CSS,  DEST_DIR / 'etf.css'),
        (SRC_JS,   DEST_DIR / 'etf.js'),
        (SRC_LW,   DEST_DIR / 'lightweight-charts.standalone.production.js'),
    ]:
        shutil.copy2(src, dst)
        print(f"  ✓ {src.name} -> {dst.relative_to(PROJECT_ROOT)}")

    # 修复 HTML 中的 css 路径（从 css/kline.css 改为 etf.css）
    html_content = SRC_HTML.read_text(encoding='utf-8')
    html_content = html_content.replace('href="css/kline.css"', 'href="etf.css"')
    html_content = html_content.replace('src="js/etf.js"', 'src="etf.js"')
    html_content = html_content.replace('src="lightweight-charts.standalone.production.js"', 'src="lightweight-charts.standalone.production.js"')
    with open(DEST_HTML, 'w', encoding='utf-8') as f:
        f.write(html_content)
    print(f"  ✓ etf.html 生成到 {DEST_HTML.relative_to(PROJECT_ROOT)}")

if __name__ == '__main__':
    gen()
