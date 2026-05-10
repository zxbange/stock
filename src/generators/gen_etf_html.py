#!/usr/bin/env python3
"""生成ETF K线浏览HTML页面"""
import os, json
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
ETF_DATA_DIR = PROJECT_ROOT / "data_etf"
KLINE_DIR    = "/data_etf/kline/"
HTML_OUT     = ETF_DATA_DIR / "index.html"

def gen_html():
    import csv as csv_module

    # 读取ETF列表
    etf_list_path = ETF_DATA_DIR / "etf_list.csv"
    bench_data = {}
    skipped = 0
    with open(etf_list_path) as f:
        for row in csv_module.DictReader(f):
            ts_code = row['ts_code'].strip()
            name    = row['name'].strip()
            bench   = row.get('benchmark', '') or '未知指数'
            amount  = float(row.get('amount') or 0)
            # 只包含有K线图的ETF
            kline_path = ETF_DATA_DIR / "kline" / f"kline_{ts_code}.png"
            if not kline_path.exists():
                skipped += 1
                continue
            bench_data.setdefault(bench, []).append({
                'ts_code': ts_code,
                'name': name,
                'benchmark': bench,
                'amount': amount
            })

    bench_js = json.dumps(bench_data, ensure_ascii=False)

    total_etfs = sum(len(v) for v in bench_data.values())
    print(f"分组: {len(bench_data)}, 有K线图ETF: {total_etfs}, 跳过(无K线): {skipped}")

    html = f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ETF K线浏览</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'PingFang SC','Microsoft YaHei',sans-serif;background:#f5f5f5;padding:20px}}
h1{{text-align:center;margin-bottom:20px;color:#333}}
.search{{text-align:center;margin-bottom:20px}}
.search input{{width:300px;padding:8px 14px;font-size:14px;border:1px solid #ccc;border-radius:20px;outline:none}}
.search input:focus{{border-color:#19c100}}
.bench{{margin-bottom:28px}}
.bench-title{{font-size:13px;color:#666;margin-bottom:8px;padding:6px 12px;background:#dde;border-radius:4px;cursor:pointer;user-select:none;display:flex;align-items:center}}
.bench-title:hover{{background:#cce}}
.bench-title .count{{margin-left:auto;color:#999;font-size:12px;font-weight:normal}}
.etf-grid{{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:10px}}
.etf-card{{background:white;border-radius:8px;padding:8px 14px;cursor:pointer;box-shadow:0 1px 4px rgba(0,0,0,0.1);transition:box-shadow .2s;min-width:120px}}
.etf-card:hover{{box-shadow:0 4px 12px rgba(0,0,0,0.22)}}
.etf-name{{font-size:13px;color:#222;font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:160px}}
.etf-code{{font-size:11px;color:#aaa;margin-top:2px}}
.etf-amt{{font-size:11px;color:#19c100;margin-top:2px}}
#modal{{display:none;position:fixed;inset:0;z-index:1000;background:rgba(0,0,0,0.75);justify-content:center;align-items:center}}
#modal.show{{display:flex}}
#modal-inner{{position:relative;background:white;border-radius:10px;max-width:98vw;max-height:98vh;overflow:auto}}
#modal-close{{position:absolute;top:6px;right:10px;font-size:30px;color:#999;cursor:pointer;line-height:1;z-index:10}}
#modal-close:hover{{color:#333}}
#modal-img{{display:block;max-width:95vw;max-height:88vh;object-fit:contain}}
#modal-title{{position:sticky;bottom:0;left:0;right:0;background:rgba(255,255,255,0.97);padding:10px 16px;font-size:13px;color:#444;border-top:1px solid #eee}}
</style>
</head>
<body>
<h1>ETF K线浏览 <span style="font-size:14px;color:#888;font-weight:normal">({total_etfs}只ETF)</span></h1>
<div class="search"><input type="text" id="searchInput" placeholder="搜索ETF名称或代码…" oninput="filter()"></div>
<div id="container"></div>
<div id="modal" onclick="if(event.target===this)closeModal()">
  <div id="modal-inner">
    <span id="modal-close" onclick="closeModal()">×</span>
    <img id="modal-img" src="" alt="K线">
    <div id="modal-title"></div>
  </div>
</div>
<script>
const KLINE_DIR = "{KLINE_DIR}";
const benchMap = {bench_js};
const allCards = [];

function render(){{
  const container = document.getElementById("container");
  container.innerHTML = "";
  allCards.length = 0;
  Object.entries(benchMap).sort((a,b)=>b[1].length-a[1].length).forEach(([bench, list])=>{{
    const benchDiv = document.createElement("div");
    benchDiv.className = "bench";
    const title = document.createElement("div");
    title.className = "bench-title";
    const shortBench = bench.length > 60 ? bench.slice(0,60)+"…" : bench;
    title.innerHTML = shortBench + ' <span class="count">(' + list.length + "只)</span>";
    title.onclick = () => grid.style.display = grid.style.display ? "" : "none";
    benchDiv.appendChild(title);
    const grid = document.createElement("div");
    grid.className = "etf-grid";
    list.sort((a,b)=>b.amount-a.amount).forEach(etf=>{{
      const card = document.createElement("div");
      card.className = "etf-card";
      card.dataset.name = etf.name;
      card.dataset.code = etf.ts_code;
      card.innerHTML = `<div class="etf-name" title="\(${{etf.name}}\)">\(${{etf.name}}\)</div>
        <div class="etf-code">\(${{etf.ts_code}}\)</div>
        <div class="etf-amt">\(${{etf.amount>0?(etf.amount/10000).toFixed(0)+'亿':''}}\)</div>`;
      card.onclick = () => openModal(etf);
      allCards.push(card);
      grid.appendChild(card);
    }});
    benchDiv.appendChild(grid);
    container.appendChild(benchDiv);
  }});
}}

function filter(){{
  const q = document.getElementById("searchInput").value.toLowerCase();
  allCards.forEach(c=>{{
    const match = !q || c.dataset.name.toLowerCase().includes(q) || c.dataset.code.toLowerCase().includes(q);
    c.style.display = match ? "" : "none";
  }});
}}

window.openModal = function(etf){{
  const img = document.getElementById("modal-img");
  img.src = KLINE_DIR + "kline_" + etf.ts_code + ".png";
  img.onerror = () => img.src = "data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' width='600' height='400'><text x='50%25' y='50%25' text-anchor='middle' dy='.3em' fill='%23999' font-size='20'>暂无K线图</text></svg>";
  document.getElementById("modal-title").textContent = etf.name + " (" + etf.ts_code + ")  |  " + etf.benchmark;
  document.getElementById("modal").classList.add("show");
  document.getElementById("modal-inner").scrollTop = 0;
}};
window.closeModal = function(){{document.getElementById("modal").classList.remove("show");}};
document.addEventListener("keydown", e=>{{if(e.key==="Escape")closeModal()}});
render();
</script>
</body>
</html>"""

    with open(HTML_OUT, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"HTML已生成: {HTML_OUT}")


if __name__ == '__main__':
    gen_html()
