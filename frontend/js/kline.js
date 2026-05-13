// Four chart instances
var ch1 = null, ch2 = null, ch3 = null, ch4 = null;
var _rows = null, _ind = null;
var cd1 = null, vl = null, difL = null, deaL = null, macdB = null, kL = null, dL = null, jL = null;
var _curCode = null, _curPeriod = 'D';
var _sidebarCollapsed = false;

var _maWindows = [5,10,20,30,60,120,240];
var _maColors = {5:'#ffea00',10:'#ff9800',20:'#00bcd4',30:'#e040fb',60:'#00e676',120:'#888888',240:'#666666'};
var _maLines = {};

var _allStocks = [];  // [{code, name, strat}]
var _stockNames = {};

// 加载股票中文名
(function() {
  fetch('/stock_names.json?v=210535').then(function(r) { return r.json(); })
  .then(function(names) {
    _stockNames = names;
  }).catch(function() {});
})();

// 解析 URL 参数 ?date=YYYYMMDD，支撑历史日期查看
var _baseDir = '/today/';
var _viewDate = null;
(function() {
  var q = location.search.match(/date=([0-9]{8})/);
  if (q) {
    _viewDate = q[1];
    _baseDir = '/' + _viewDate + '/';
  }
  // debug removed
})();

var _alias = {
  '补票': '补票龙', 'TePu': '回头龙', '填坑': '填坑龙',
  '大波浪': '大波龙', '红悬停': '跳高龙', '高业绩': '实力龙'
};
var _icons = {
  '补票':'📈','TePu':'🔁','填坑':'🕳️','大波浪':'🌊','红悬停':'🦘','高业绩':'💎'
};

// 从 result_*.txt 动态构建侧边栏
function loadSidebar() {
  var strats = ['补票','TePu','填坑','大波浪','红悬停','高业绩'];
  var loaded = 0, total = 0;
  var byStrat = {};

  strats.forEach(function(strat) {
    fetch(_baseDir + 'result_' + strat + '.txt').then(function(r) {
      if (!r.ok) return [];
      return r.text();
    }).then(function(text) {
      var lines = text.trim().split('\n');
      // 首行是战法名，跳过
      var codes = lines.slice(1).filter(function(l) { return /^\d{6}\.(SZ|SH|BJ)$/.test(l.trim()); });
      byStrat[strat] = codes;
      loaded++;
      if (loaded === strats.length) {
        buildSidebar(byStrat);
      }
    }).catch(function() {
      byStrat[strat] = [];
      loaded++;
      if (loaded === strats.length) buildSidebar(byStrat);
    });
  });
}

function buildSidebar(byStrat) {
  _allStocks = [];
  var html = '';
  var totalCnt = 0;

  var order = ['补票','TePu','填坑','大波浪','红悬停','高业绩'];
  order.forEach(function(strat) {
    var codes = byStrat[strat] || [];
    if (codes.length === 0) return;
    var name = _alias[strat] || strat;
    var icon = _icons[strat] || '📌';
    totalCnt += codes.length;
    html += '<div class="group">';
    html += '<div class="ghdr" onclick="toggleGroup(this)"><span class="gname">' + name + '</span><span class="gcnt">' + codes.length + '</span></div>';
    html += '<div class="stocks">';
    codes.forEach(function(code) {
      var cname = _stockNames[code] || code;
      _allStocks.push({code: code, name: cname, strat: strat});
      html += '<div class="stk" data-code="' + code + '" onclick="selectStock(this,\'' + code + '\')">';
      html += '<div class="sname">' + cname + '</div>';
      html += '<div class="scode">' + code + '</div></div>';
    });
    html += '</div></div>\n';
  });

  document.getElementById('sidebarTitle').innerHTML = 'K线精选<br><span style="font-size:10px;color:#666">' + totalCnt + '只</span>';
  document.getElementById('sidebarContent').innerHTML = html;

  // 自动展开第一组、选中第一只
  var firstGroup = document.querySelector('.stocks');
  if (firstGroup) firstGroup.classList.add('open');
  var firstStk = document.querySelector('.stk');
  if (firstStk) selectStock(firstStk, firstStk.dataset.code);
}

function createCharts() {
  if (ch1 !== null) return;

  var w = document.getElementById('p1').clientWidth || 800;
  var h1 = 430, h2 = 100, h3 = 100, h4 = 100;

  ch1 = LightweightCharts.createChart(document.getElementById('p1'), {
    width: w, height: h1,
    layout: { background: { color: '#111122' }, textColor: '#888' },
    grid: { vertLines: { color: '#1e1e2e' }, horzLines: { color: '#1e1e2e' } },
    rightPriceScale: { borderVisible: false, visible: false },
    timeScale: { borderVisible: false, timeVisible: true, rightOffset: 5 },
    crosshair: { mode: LightweightCharts.CrosshairMode.Normal }
  });
  cd1 = ch1.addCandlestickSeries({
    upColor: '#ef5350', downColor: '#26a69a',
    borderUpColor: '#ef5350', borderDownColor: '#26a69a',
    wickUpColor: '#ef5350', wickDownColor: '#26a69a',
    priceLineVisible: false, lastValueVisible: false
  });
  _maWindows.forEach(function(n) {
    _maLines[n] = ch1.addLineSeries({
      color: _maColors[n], lineWidth: 0.5,
      priceLineVisible: false, lastValueVisible: false, opacity: 0.7
    });
  });

  ch2 = LightweightCharts.createChart(document.getElementById('p2'), {
    width: w, height: h2,
    layout: { background: { color: '#111122' }, textColor: '#888' },
    grid: { vertLines: { color: '#1e1e2e' }, horzLines: { color: '#1e1e2e' } },
    rightPriceScale: { borderVisible: false, visible: false },
    timeScale: { borderVisible: false }
  });
  vl = ch2.addHistogramSeries({ priceFormat: { type: 'volume' }, priceLineVisible: false, lastValueVisible: false });

  ch3 = LightweightCharts.createChart(document.getElementById('p3'), {
    width: w, height: h3,
    layout: { background: { color: '#111122' }, textColor: '#888' },
    grid: { vertLines: { color: '#1e1e2e' }, horzLines: { color: '#1e1e2e' } },
    rightPriceScale: { borderVisible: false, visible: false },
    timeScale: { borderVisible: false }
  });
  difL = ch3.addLineSeries({ color: '#ff9800', lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
  deaL = ch3.addLineSeries({ color: '#00bcd4', lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
  macdB = ch3.addHistogramSeries({ priceLineVisible: false, lastValueVisible: false });

  ch4 = LightweightCharts.createChart(document.getElementById('p4'), {
    width: w, height: h4,
    layout: { background: { color: '#111122' }, textColor: '#888' },
    grid: { vertLines: { color: '#1e1e2e' }, horzLines: { color: '#1e1e2e' } },
    rightPriceScale: { borderVisible: false, visible: false },
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

  // Crosshair info
  ch1.subscribeCrosshairMove(function(param) {
    if (!param.time || !_rows) return;
    var idx = -1;
    for (var i = 0; i < _rows.length; i++) { if (_rows[i].time === param.time) { idx = i; break; } }
    if (idx < 0) return;
    var r = _rows[idx], ind = _ind;
    var prev = idx > 0 ? _rows[idx-1] : r;
    var pct = ((r.c - prev.c) / prev.c * 100);
    var pctStr = (pct >= 0 ? '+' : '') + pct.toFixed(2) + '%';
    var pctCls = pct >= 0 ? '#ef5350' : '#26a69a';
    var info1 = '<div>收:<span style="color:#fff">' + f2(r.c) + '</span> 开:' + f2(r.o) + ' 高:' + f2(r.h) + ' 低:' + f2(r.l) + ' <span style="color:' + pctCls + '">涨幅∶' + pctStr + '</span></div><div>';
    [5,10,20,30].forEach(function(n) {
      var v = ind['ma' + n] ? ind['ma' + n][idx] : null;
      info1 += '<span style="color:' + _maColors[n] + '">MA' + n + ':' + f2(v) + '</span> ';
    });
    info1 += '</div><div>';
    [60,120,240].forEach(function(n) {
      var v = ind['ma' + n] ? ind['ma' + n][idx] : null;
      info1 += '<span style="color:' + _maColors[n] + '">MA' + n + ':' + f2(v) + '</span> ';
    });
    info1 += '</div>';
    setInfo('info1', info1);
    setInfo('info2', '<div>成交量 <span style="color:#fff">' + fv(r.v||0) + '</span></div>');
    if (ind.dif) {
      setInfo('info3', '<div>DIF:<span style="color:#ff9800">' + f2(ind.dif[idx]) + '</span> DEA:<span style="color:#00bcd4">' + f2(ind.dea[idx]) + '</span> MACD:<span style="color:#fff">' + f2(ind.macd ? ind.macd[idx] : null) + '</span></div>');
    }
    if (ind.K) {
      setInfo('info4', '<div>K:<span style="color:#ffea00">' + f2(ind.K[idx]) + '</span> D:<span style="color:#ff9800">' + f2(ind.D[idx]) + '</span> J:<span style="color:#e040fb">' + f2(ind.J ? ind.J[idx] : null) + '</span></div>');
    }
  });
}

function setInfo(id, html) {
  var el = document.getElementById(id);
  if (el) el.innerHTML = html;
}

function syncResize() {
  if (!ch1) { createCharts(); return; }
  var w = document.getElementById('p1').clientWidth || 800;
  ch1.resize(w, 430); ch2.resize(w, 100); ch3.resize(w, 100); ch4.resize(w, 100);
}

function loadData(code, period) {
  var file = period === 'D' ? code + '.json' : code + '_' + period.toLowerCase() + '.json';
  document.getElementById('loading').classList.add('show');
  fetch(_baseDir + 'indicators/' + file).then(function(r) {
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
    // 不弹窗，避免用户看到一串加载失败提示
  });
}

function f2(v) { return v == null ? '--' : v.toFixed(2); }
function fv(v) { return v == null ? '--' : (v >= 10000 ? (v/10000).toFixed(0) + '万' : v.toFixed(0)); }

function render(rows, ind, period) {
  _rows = rows; _ind = ind;
  var N = rows.length, last = rows[N-1], prev = rows[N-2] || last;
  var pct = ((last.c - prev.c) / prev.c * 100);
  var pctStr = (pct >= 0 ? '+' : '') + pct.toFixed(2) + '%';
  var pctCls = pct >= 0 ? '#ef5350' : '#26a69a';

  // Pane 1
  var info1 = '<div>收:<span style="color:#fff">' + f2(last.c) + '</span> 开:' + f2(last.o) + ' 高:' + f2(last.h) + ' 低:' + f2(last.l) + ' <span style="color:' + pctCls + '">涨幅∶' + pctStr + '</span></div><div>';
  [5,10,20,30].forEach(function(n) {
    var v = ind['ma' + n] ? ind['ma' + n][N-1] : null;
    info1 += '<span style="color:' + _maColors[n] + '">MA' + n + ':' + f2(v) + '</span> ';
  });
  info1 += '</div><div>';
  [60,120,240].forEach(function(n) {
    var v = ind['ma' + n] ? ind['ma' + n][N-1] : null;
    info1 += '<span style="color:' + _maColors[n] + '">MA' + n + ':' + f2(v) + '</span> ';
  });
  info1 += '</div>';
  setInfo('info1', info1);

  cd1.setData(rows.map(function(r) { return { time: r.time, open: r.o, high: r.h, low: r.l, close: r.c }; }));
  _maWindows.forEach(function(n) {
    var key = 'ma' + n;
    if (ind[key]) {
      _maLines[n].setData(rows.map(function(r, i) {
        return { time: r.time, value: ind[key][i] };
      }).filter(function(d) { return d.value != null; }));
    }
  });

  // Pane 2
  vl.setData(rows.map(function(r) {
    return { time: r.time, value: r.v || 0, color: r.c >= r.o ? '#ef5350' : '#26a69a' };
  }));
  setInfo('info2', '<div>成交量 <span style="color:#fff">' + fv(last.v||0) + '</span></div>');

  // Pane 3
  if (ind.dif) {
    difL.setData(rows.map(function(r, i) { return { time: r.time, value: ind.dif[i] }; }).filter(function(d) { return d.value != null; }));
    deaL.setData(rows.map(function(r, i) { return { time: r.time, value: ind.dea[i] }; }).filter(function(d) { return d.value != null; }));
    macdB.setData(rows.map(function(r, i) {
      var v = ind.macd ? ind.macd[i] : null;
      return { time: r.time, value: v != null ? v : 0, color: v >= 0 ? '#ef535088' : '#26a69a88' };
    }));
    setInfo('info3', '<div>DIF:<span style="color:#ff9800">' + f2(ind.dif[N-1]) + '</span> DEA:<span style="color:#00bcd4">' + f2(ind.dea[N-1]) + '</span> MACD:<span style="color:#fff">' + f2(ind.macd ? ind.macd[N-1] : null) + '</span></div>');
  }

  // Pane 4
  if (ind.K) {
    kL.setData(rows.map(function(r, i) { return { time: r.time, value: ind.K[i] }; }).filter(function(d) { return d.value != null; }));
    dL.setData(rows.map(function(r, i) { return { time: r.time, value: ind.D[i] }; }).filter(function(d) { return d.value != null; }));
    jL.setData(rows.map(function(r, i) { return { time: r.time, value: ind.J ? ind.J[i] : null }; }).filter(function(d) { return d.value != null; }));
    setInfo('info4', '<div>K:<span style="color:#ffea00">' + f2(ind.K[N-1]) + '</span> D:<span style="color:#ff9800">' + f2(ind.D[N-1]) + '</span> J:<span style="color:#e040fb">' + f2(ind.J ? ind.J[N-1] : null) + '</span></div>');
  }

  // 默认显示最新200根蜡烛，左边留5根空位作右边距效果
  var COUNT = 200;
  var fromIdx = Math.max(0, N - COUNT);
  var toIdx = N - 1;
  try {
    ch1.timeScale().setVisibleRange({ from: rows[fromIdx].time, to: rows[toIdx].time });
    ch2.timeScale().setVisibleRange({ from: rows[fromIdx].time, to: rows[toIdx].time });
    ch3.timeScale().setVisibleRange({ from: rows[fromIdx].time, to: rows[toIdx].time });
    ch4.timeScale().setVisibleRange({ from: rows[fromIdx].time, to: rows[toIdx].time });
  } catch(e) { ch1.timeScale().fitContent(); }
}

function selectStock(el, code) {
  document.querySelectorAll('.stk').forEach(function(s) { s.classList.remove('active'); });
  el.classList.add('active');
  _curCode = code;
  var nameEl = el.querySelector('.sname');
  var codeEl = el.querySelector('.scode');
  document.getElementById('title-name').textContent = nameEl ? nameEl.textContent : code;
  document.getElementById('title-code').textContent = codeEl ? codeEl.textContent : code;
  createCharts();
  loadData(code, _curPeriod);
}

function setPeriod(p) {
  _curPeriod = p;
  document.querySelectorAll('.ptab').forEach(function(b) { b.classList.toggle('active', b.dataset.p === p); });
  if (_curCode) { createCharts(); loadData(_curCode, p); }
}

function toggleGroup(el) { el.nextElementSibling.classList.toggle('open'); }

function prevStock() { navigateStock(-1); }
function nextStock() { navigateStock(+1); }
function navigateStock(dir) {
  var active = document.querySelector('.stk.active');
  if (!active) return;
  var items = Array.from(active.parentElement.querySelectorAll('.stk'));
  var idx = items.indexOf(active);
  var newIdx = (idx + dir + items.length) % items.length;
  var next = items[newIdx];
  if (next) { next.click(); next.scrollIntoView({ block: 'nearest', behavior: 'smooth' }); }
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

// 页面加载：先构建侧边栏，再自动选第一只
document.addEventListener('DOMContentLoaded', function() {
  // 注入 info 元素到各 pane
  ['p1','p2','p3','p4'].forEach(function(id) {
    var el = document.getElementById(id);
    if (el && !document.getElementById('info' + id[1])) {
      var info = document.createElement('div');
      info.className = 'pane-info';
      info.id = 'info' + id[1];
      el.appendChild(info);
    }
  });
  // 先等股票名加载完，再构建侧栏
  function tryLoad() {
    if (Object.keys(_stockNames).length > 0) {
      loadSidebar();
    } else {
      setTimeout(tryLoad, 50);
    }
  }
  tryLoad();
});