#!/usr/bin/env python3
"""生成股票K线页面 - 四面板专业版 v2"""
import os, re, json
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
today_dir = PROJECT_ROOT / 'daily_result' / 'today'
today_dir.mkdir(parents=True, exist_ok=True)
IND_DIR = today_dir / 'indicators'

strategy_files = {
    '补票': today_dir / 'result_补票.txt',
    'TePu': today_dir / 'result_TePu.txt',
    '填坑': today_dir / 'result_填坑.txt',
    '大波浪': today_dir / 'result_大波浪.txt',
    '红悬停': today_dir / 'result_红悬停.txt',
    '业绩稳增': today_dir / 'result_业绩稳增.txt',
}

stocks = []
for strat, fpath in strategy_files.items():
    if fpath.exists():
        with open(fpath) as f:
            lines = [l.strip() for l in f]
        codes = [l for l in lines if re.match(r'^\d{6}\.(?:SZ|SH|BJ)$', l)]
        for code in codes:
            stocks.append((code, strat))

name_map = {}
try:
    import tushare as ts
    pro = ts.pro_api()
    mdf = pro.stock_basic(exchange='', list_status='L', fields='ts_code,name')
    for _, row in mdf.iterrows():
        name_map[row['ts_code']] = row['name']
except Exception as e:
    print(f"获取名称: {e}")
for code, _ in stocks:
    if code not in name_map:
        name_map[code] = code

by_strat = {}
for code, strat in stocks:
    by_strat.setdefault(strat, []).append(code)

icons = {'补票': '📈', 'TePu': '📊', '填坑': '🕳️', '大波浪': '🌊', '红悬停': '🔴', '业绩稳增': '💰'}
alias = {'补票': '补票战法', 'TePu': 'TePu战法', '填坑': '填坑战法', '大波浪': '大波浪战法', '红悬停': '红悬停战法', '业绩稳增': '业绩稳增战法'}

def get_result_count():
    counts = {}
    for strat, fpath in strategy_files.items():
        if fpath.exists():
            with open(fpath) as f:
                lines = [l.strip() for l in f]
            counts[strat] = len([l for l in lines if re.match(r'^\d{6}\.(?:SZ|SH|BJ)$', l)])
    return counts

counts = get_result_count()
total = sum(counts.values())

html = f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<title>K线精选 {datetime.now().strftime('%Y-%m-%d')}</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
html,body{{height:100%;overflow:hidden;background:#111;font-family:'PingFang SC','Microsoft YaHei',sans-serif}}
.wrap{{display:flex;height:100vh}}
.sidebar{{width:160px;background:#1a1a2e;border-right:1px solid #2a2a3e;overflow-y:auto;flex-shrink:0;transition:width .25s}}.sidebar.collapsed{{width:0;overflow:hidden}}
.sidebar h2{{font-size:13px;color:#888;padding:10px 12px 6px;font-weight:400}}
.group{{margin-bottom:4px}}
.ghdr{{padding:6px 12px;font-size:13px;color:#fff;cursor:pointer;user-select:none;display:flex;justify-content:space-between;align-items:center}}
.ghdr:hover{{background:#252540}}
.ghdr .gname{{display:flex;align-items:center;gap:5px}}
.ghdr .gcnt{{font-size:11px;color:#666;background:#252540;padding:1px 6px;border-radius:8px}}
.stocks{{display:none;padding:2px 0}}
.stocks.open{{display:block}}
.stk{{padding:5px 12px 5px 28px;font-size:12px;color:#ccc;cursor:pointer;border-left:2px solid transparent}}
.stk:hover{{background:#252540;color:#fff}}
.stk.active{{background:#252540;color:#ffea00;border-left-color:#ffea00}}
.stk .sname{{}}
.stk .scode{{font-size:10px;color:#666;margin-top:1px}}
.main{{flex:1;display:flex;flex-direction:column;min-width:0;overflow:hidden}}
.topbar{{background:#1a1a2e;border-bottom:1px solid #2a2a3e;padding:8px 14px;display:flex;align-items:center;gap:16px;flex-shrink:0;height:48px}}
.stk-title{{font-size:13px;color:#fff;font-weight:bold;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:180px}}
.stk-sub{{font-size:11px;color:#666;margin-top:2px}}
.period-tabs{{display:flex;gap:3px;margin-left:auto}}
.ptab{{padding:4px 14px;font-size:12px;color:#888;background:#252540;border:none;border-radius:4px;cursor:pointer}}
.ptab.active{{background:#ffea00;color:#111;font-weight:bold}}
#panes{{display:flex;flex-direction:column;flex:1;min-height:0}}
.pane{{position:relative;min-height:0;flex-shrink:0;background:#111122}}
#p1{{height:500px;border-bottom:1px solid #1e1e2e}}
#p2{{height:100px;border-bottom:1px solid #1e1e2e}}
#p3{{height:100px;border-bottom:1px solid #1e1e2e}}
#p4{{height:100px}}
.pane-info{{position:absolute;top:4px;left:8px;z-index:5;font-size:10px;color:#888;pointer-events:none;line-height:1.7;white-space:nowrap}}
#loading{{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);color:#555;font-size:13px;display:none;z-index:20;background:#111122;padding:8px 16px;border-radius:4px}}
#loading.show{{display:block}}
</style>
</head>
<body>
<div class="wrap">
  <div class="sidebar">
    <h2>K线精选 · {total}只</h2>
"""

for strat, codes in by_strat.items():
    icon = icons.get(strat, '📌')
    name = alias.get(strat, strat)
    cnt = counts.get(strat, len(codes))
    html += f'<div class="group">\n'
    html += f'<div class="ghdr" onclick="toggleGroup(this)"><span class="gname">{icon} {name}</span><span class="gcnt">{cnt}</span></div>\n'
    html += '<div class="stocks">\n'
    for code in codes:
        cname = name_map.get(code, code)
        html += f'<div class="stk" data-code="{code}" onclick="selectStock(this,\'{code}\')"><div class="sname">{cname}</div><div class="scode">{code}</div></div>\n'
    html += '</div>\n</div>\n'

html += """  </div>

  <div class="main">
    <div class="topbar">
      <span id="sidebar-arrow" onclick="toggleSidebar()" style="cursor:pointer;font-size:16px;color:#888;margin-right:10px;flex-shrink:0" title="展开/收起侧栏">&#x25C0;</span>
      <div>
        <div class="stk-title" id="title-name">--</div>
        <div class="stk-sub" id="title-code">--</div>
      </div>
      <div class="period-tabs">
        <button class="ptab active" data-p="D" onclick="setPeriod('D')">日K</button>
        <button class="ptab" data-p="W" onclick="setPeriod('W')">周K</button>
        <button class="ptab" data-p="M" onclick="setPeriod('M')">月K</button>
      </div>
    </div>
    <div id="panes">
      <div class="pane" id="p1"><div class="pane-info" id="info1"></div></div>
      <div class="pane" id="p2"><div class="pane-info" id="info2"></div></div>
      <div class="pane" id="p3"><div class="pane-info" id="info3"></div></div>
      <div class="pane" id="p4"><div class="pane-info" id="info4"></div></div>
      <div id="loading">加载中...</div>
    </div>
  </div>
</div>
<script src="lightweight-charts.standalone.production.js"></script>
<script>
// Four chart instances
var ch1 = null, ch2 = null, ch3 = null, ch4 = null;
var cd1 = null, vl = null, difL = null, deaL = null, macdB = null, kL = null, dL = null, jL = null;
var _curCode = null, _curPeriod = 'D';
var _sidebarCollapsed = false;

var _maWindows = [5,10,20,30,60];
var _maColors = {5:'#ffea00',10:'#ff9800',20:'#00bcd4',30:'#e040fb',60:'#00e676'};
var _maLines = {};

function createCharts() {
  if (ch1 !== null) return; // already created

  var w = document.getElementById('p1').clientWidth || 800;
  var h1 = 500, h2 = 100, h3 = 100, h4 = 100;

  // K线 chart
  ch1 = LightweightCharts.createChart(document.getElementById('p1'), {
    width: w, height: h1,
    layout: { background: { color: '#111122' }, textColor: '#888' },
    grid: { vertLines: { color: '#1e1e2e' }, horzLines: { color: '#1e1e2e' } },
    rightPriceScale: { borderVisible: false },
    timeScale: { borderVisible: false, timeVisible: true },
    crosshair: { mode: LightweightCharts.CrosshairMode.Normal }
  });
  cd1 = ch1.addCandlestickSeries({
    upColor: '#ef5350', downColor: '#26a69a',
    borderUpColor: '#ef5350', borderDownColor: '#26a69a',
    wickUpColor: '#ef5350', wickDownColor: '#26a69a',
    priceLineVisible: false, lastValueVisible: false
  });
  // MA lines on K线 chart
  _maWindows.forEach(function(n) {
    _maLines[n] = ch1.addLineSeries({
      color: _maColors[n], lineWidth: 1,
      priceLineVisible: false, lastValueVisible: false
    });
  });

  // 成交量 chart
  ch2 = LightweightCharts.createChart(document.getElementById('p2'), {
    width: w, height: h2,
    layout: { background: { color: '#111122' }, textColor: '#888' },
    grid: { vertLines: { color: '#1e1e2e' }, horzLines: { color: '#1e1e2e' } },
    rightPriceScale: { borderVisible: false },
    timeScale: { borderVisible: false }
  });
  vl = ch2.addHistogramSeries({
    priceFormat: { type: 'volume' },
    priceLineVisible: false, lastValueVisible: false
  });

  // MACD chart
  ch3 = LightweightCharts.createChart(document.getElementById('p3'), {
    width: w, height: h3,
    layout: { background: { color: '#111122' }, textColor: '#888' },
    grid: { vertLines: { color: '#1e1e2e' }, horzLines: { color: '#1e1e2e' } },
    rightPriceScale: { borderVisible: false },
    timeScale: { borderVisible: false }
  });
  difL = ch3.addLineSeries({ color: '#ff9800', lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
  deaL = ch3.addLineSeries({ color: '#00bcd4', lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
  macdB = ch3.addHistogramSeries({ priceLineVisible: false, lastValueVisible: false });

  // KDJ chart
  ch4 = LightweightCharts.createChart(document.getElementById('p4'), {
    width: w, height: h4,
    layout: { background: { color: '#111122' }, textColor: '#888' },
    grid: { vertLines: { color: '#1e1e2e' }, horzLines: { color: '#1e1e2e' } },
    rightPriceScale: { borderVisible: false },
    timeScale: { borderVisible: false }
  });
  kL = ch4.addLineSeries({ color: '#ffea00', lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
  dL = ch4.addLineSeries({ color: '#ff9800', lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
  jL = ch4.addLineSeries({ color: '#e040fb', lineWidth: 1, priceLineVisible: false, lastValueVisible: false });

  // Sync time scales
  ch1.timeScale().subscribeVisibleLogicalRangeChange(function(range) {
    if (range) {
      try { ch2.timeScale().setVisibleLogicalRange(range); } catch(e) {}
      try { ch3.timeScale().setVisibleLogicalRange(range); } catch(e) {}
      try { ch4.timeScale().setVisibleLogicalRange(range); } catch(e) {}
    }
  });
}

function syncResize() {
  if (!ch1) { createCharts(); return; }
  var w = document.getElementById('p1').clientWidth || 800;
  ch1.resize(w, 500);
  ch2.resize(w, 100);
  ch3.resize(w, 100);
  ch4.resize(w, 100);
}

function loadData(code, period) {
  var file = period === 'D' ? code + '.json' : code + '_' + period.toLowerCase() + '.json';
  document.getElementById('loading').classList.add('show');
  fetch('indicators/' + file).then(function(r) {
    if (!r.ok) throw new Error('HTTP ' + r.status);
    return r.json();
  }).then(function(data) {
    document.getElementById('loading').classList.remove('show');
    var rows = data.rows || data.kline;
    var ind = data.indicators || data.ind;
    if (!rows || !ind) { alert('数据格式错误'); return; }
    render(rows, ind, period);
  }).catch(function(e) {
    document.getElementById('loading').classList.remove('show');
    alert('加载失败: ' + e.message);
  });
}

function f2(v) { return v == null ? '--' : v.toFixed(2); }
function fv(v) { return v == null ? '--' : (v >= 10000 ? (v/10000).toFixed(0) + '万' : v.toFixed(0)); }

function render(rows, ind, period) {
  var N = rows.length;
  var last = rows[N-1];
  var prev = rows[N-2] || last;
  var pct = ((last.c - prev.c) / prev.c * 100);
  var pctStr = (pct >= 0 ? '+' : '') + pct.toFixed(2) + '%';
  var pctCls = pct >= 0 ? '#ef5350' : '#26a69a';

  // === Pane 1: K线 info ===
  var info1 = '<div>收:<span style="color:#fff">' + f2(last.c) + '</span> 开:' + f2(last.o) + ' 高:' + f2(last.h) + ' 低:' + f2(last.l) + ' <span style="color:' + pctCls + '">' + pctStr + ' (涨幅)</span></div><div>';
  _maWindows.forEach(function(n) {
    var v = ind['ma' + n] ? ind['ma' + n][N-1] : null;
    info1 += '<span style="color:' + _maColors[n] + '">MA' + n + ':' + f2(v) + '</span> ';
  });
  info1 += '</div>';
  document.getElementById('info1').innerHTML = info1;

  // K线 + MA
  cd1.setData(rows.map(function(r) {
    return { time: r.time, open: r.o, high: r.h, low: r.l, close: r.c };
  }));
  _maWindows.forEach(function(n) {
    var key = 'ma' + n;
    if (ind[key]) {
      _maLines[n].setData(rows.map(function(r, i) {
        return { time: r.time, value: ind[key][i] };
      }).filter(function(d) { return d.value != null; }));
    }
  });

  // === Pane 2: Volume ===
  vl.setData(rows.map(function(r) {
    return { time: r.time, value: r.v || 0, color: r.c >= r.o ? '#ef535050' : '#26a69a50' };
  }));
  document.getElementById('info2').innerHTML = '<div>成交量 <span style="color:#fff">' + fv(last.v || 0) + '</span></div>';

  // === Pane 3: MACD ===
  if (ind.dif) {
    difL.setData(rows.map(function(r, i) {
      return { time: r.time, value: ind.dif[i] };
    }).filter(function(d) { return d.value != null; }));
    deaL.setData(rows.map(function(r, i) {
      return { time: r.time, value: ind.dea[i] };
    }).filter(function(d) { return d.value != null; }));
    macdB.setData(rows.map(function(r, i) {
      var v = ind.macd ? ind.macd[i] : null;
      return { time: r.time, value: v != null ? v : 0, color: v >= 0 ? '#ef535088' : '#26a69a88' };
    }));
    var dLast = ind.dif[N-1], deaLast = ind.dea[N-1], mLast = ind.macd ? ind.macd[N-1] : null;
    document.getElementById('info3').innerHTML = '<div>DIF:<span style="color:#ff9800">' + f2(dLast) + '</span> DEA:<span style="color:#00bcd4">' + f2(deaLast) + '</span> MACD:<span style="color:#fff">' + f2(mLast) + '</span></div>';
  }

  // === Pane 4: KDJ ===
  if (ind.K) {
    kL.setData(rows.map(function(r, i) {
      return { time: r.time, value: ind.K[i] };
    }).filter(function(d) { return d.value != null; }));
    dL.setData(rows.map(function(r, i) {
      return { time: r.time, value: ind.D[i] };
    }).filter(function(d) { return d.value != null; }));
    jL.setData(rows.map(function(r, i) {
      return { time: r.time, value: ind.j ? ind.j[i] : null };
    }).filter(function(d) { return d.value != null; }));
    var kLast = ind.K[N-1], dLast2 = ind.D[N-1], jLast = ind.j ? ind.j[N-1] : null;
    document.getElementById('info4').innerHTML = '<div>K:<span style="color:#ffea00">' + f2(kLast) + '</span> D:<span style="color:#ff9800">' + f2(dLast2) + '</span> J:<span style="color:#e040fb">' + f2(jLast) + '</span></div>';
  }

  ch1.timeScale().fitContent();
}

function selectStock(el, code) {
  document.querySelectorAll('.stk').forEach(function(s) { s.classList.remove('active'); });
  el.classList.add('active');
  _curCode = code;
  document.getElementById('title-name').textContent = el.querySelector('.sname').textContent;
  document.getElementById('title-code').textContent = el.querySelector('.scode').textContent;
  createCharts();
  loadData(code, _curPeriod);
}

function setPeriod(p) {
  _curPeriod = p;
  document.querySelectorAll('.ptab').forEach(function(b) { b.classList.toggle('active', b.dataset.p === p); });
  if (_curCode) { createCharts(); loadData(_curCode, p); }
}

function toggleGroup(el) {
  el.nextElementSibling.classList.toggle('open');
}

function toggleSidebar() {
  var sb = document.querySelector('.sidebar');
  _sidebarCollapsed = !_sidebarCollapsed;
  sb.classList.toggle('collapsed', _sidebarCollapsed);
  var arrow = document.getElementById('sidebar-arrow');
  if (arrow) arrow.innerHTML = _sidebarCollapsed ? '&#x25B6;' : '&#x25C0;';
  setTimeout(syncResize, 250);
}

window.addEventListener('resize', function() {
  clearTimeout(window._resizeTimer);
  window._resizeTimer = setTimeout(syncResize, 200);
});

document.addEventListener('DOMContentLoaded', function() {
  var firstGroup = document.querySelector('.stocks');
  if (firstGroup) firstGroup.classList.add('open');
  var firstStk = document.querySelector('.stk');
  if (firstStk) selectStock(firstStk, firstStk.dataset.code);
});
</script>
</body>
</html>
"""

out_path = today_dir / 'index.html'
with open(out_path, 'w') as f:
    f.write(html)

lc_src = PROJECT_ROOT / 'data_etf' / 'lightweight-charts.standalone.production.js'
lc_dst = today_dir / 'lightweight-charts.standalone.production.js'
if lc_src.exists() and not lc_dst.exists():
    import shutil
    shutil.copy(lc_src, lc_dst)
if not lc_dst.exists() and (PROJECT_ROOT / 'frontend' / 'lightweight-charts.standalone.production.js').exists():
    import shutil
    shutil.copy(PROJECT_ROOT / 'frontend' / 'lightweight-charts.standalone.production.js', lc_dst)

print(f"生成完成: {out_path}")
for strat, cnt in counts.items():
    print(f"  {alias.get(strat,strat)}: {cnt}只")