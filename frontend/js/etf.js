// Four chart instances
var ch1 = null, ch2 = null, ch3 = null, ch4 = null;
var _rows = null, _ind = null;
var cd1 = null, vl = null, difL = null, deaL = null, macdB = null, kL = null, dL = null, jL = null;
var _curCode = null, _curPeriod = 'D';
var _sidebarCollapsed = false;
var _benchData = null;  // 存储完整的etf列表数据，用于搜索过滤

var _maWindows = [5,10,20,30,60,120,240];
var _maColors = {5:'#ffea00',10:'#ff9800',20:'#00bcd4',30:'#e040fb',60:'#00e676',120:'#888888',240:'#666666'};
var _maLines = {};

var _baseDir = '/today/';
var _viewDate = null;
var _etfBaseDir = '';

(function() {
  var q = location.search.match(/date=([0-9]{8})/);
  if (q) {
    _viewDate = q[1];
    _baseDir = '/' + _viewDate + '/';
  }
  _etfBaseDir = _baseDir + 'indicators_etf/';
})();

// ─── 侧边栏 ───────────────────────────────────────────────────────────────

function loadSidebar() {
  fetch(_baseDir + 'etf_list.json').then(function(r) { return r.json(); })
  .then(function(benchData) {
    _benchData = benchData;
    window._benchData = benchData;
    buildSidebarETF(benchData);
    document.getElementById('etfSearch').addEventListener('input', function() {
      buildSidebarETF(_benchData, this.value.trim());
    });
  }).catch(function() {});
}

function buildSidebarETF(benchData, searchText) {
  var search = (searchText || '').toLowerCase();
  var html = '';
  var totalCnt = 0;

  var benches = Object.keys(benchData).sort(function(a, b) {
    var sumA = benchData[a].reduce(function(s, x) { return s + x.amount; }, 0);
    var sumB = benchData[b].reduce(function(s, x) { return s + x.amount; }, 0);
    return sumB - sumA;
  });

  benches.forEach(function(bench) {
    var list = benchData[bench];
    if (list.length === 0) return;

    // 搜索模式下：过滤出匹配项；非搜索模式：正常显示全量
    var filteredList = list;
    if (search) {
      filteredList = list.filter(function(etf) {
        return etf.ts_code.toLowerCase().includes(search) || etf.name.toLowerCase().includes(search);
      });
    }
    if (filteredList.length === 0) return;

    totalCnt += filteredList.length;
    var shortBench = bench.length > 55 ? bench.slice(0, 55) + '…' : bench;
    html += '<div class="group">';
    html += '<div class="ghdr" onclick="toggleGroup(this)"><span class="gname">' + shortBench + '</span><span class="gcnt">' + filteredList.length + '</span></div>';
    html += '<div class="stocks">';
    filteredList.forEach(function(etf) {
      html += '<div class="stk" data-code="' + etf.ts_code + '" onclick="selectStock(this,\'' + etf.ts_code + '\')"><div class="sname">' + etf.name + '</div><div class="scode">' + etf.ts_code + '</div></div>';
    });
    html += '</div></div>';
  });

  var label = search ? 'ETF精选<span style="font-size:10px;color:#888"> · 搜索:"' + search + '" · ' + totalCnt + '只</span>' : 'ETF精选<br><span style="font-size:10px;color:#666">' + totalCnt + '只</span>';
  document.getElementById('sidebarTitle').innerHTML = label;
  document.getElementById('sidebarContent').innerHTML = html || '<div style="padding:12px;color:#888;text-align:center">无匹配结果</div>';

  if (!search) {
    var firstGroup = document.querySelector('.stocks');
    if (firstGroup) firstGroup.classList.add('open');
    var firstStk = document.querySelector('.stk');
    if (firstStk) selectStock(firstStk, firstStk.dataset.code);
  }
}

// ─── 图表创建 ───────────────────────────────────────────────────────────────

function createCharts() {
  console.log('[etf] createCharts', !!ch1);
  var w = document.getElementById('p1').clientWidth;
  var h1 = 430, h2 = 100, h3 = 100, h4 = 100;

  if (!ch1) {
    ch1 = LightweightCharts.createChart(document.getElementById('p1'), {
      width: w, height: h1,
      layout: { background: { color: '#111122' }, textColor: '#888' },
      grid: { vertLines: { color: '#1e1e2e' }, horzLines: { color: '#1e1e2e' } },
      rightPriceScale: { borderVisible: false, visible: false },
      timeScale: { borderVisible: false, timeVisible: true },
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
    vl = ch2.addHistogramSeries({ color: '#26a69a', priceLineVisible: false, lastValueVisible: false });

    ch3 = LightweightCharts.createChart(document.getElementById('p3'), {
      width: w, height: h3,
      layout: { background: { color: '#111122' }, textColor: '#888' },
      grid: { vertLines: { color: '#1e1e2e' }, horzLines: { color: '#1e1e2e' } },
      rightPriceScale: { borderVisible: false, visible: false },
      timeScale: { borderVisible: false }
    });
    difL = ch3.addLineSeries({ color: '#ff9800', lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
    deaL = ch3.addLineSeries({ color: '#00bcd4', lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
    macdB = ch3.addHistogramSeries({ color: '#888', priceLineVisible: false, lastValueVisible: false });

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

    ch1.timeScale().subscribeVisibleLogicalRangeChange(function(range) {
      if (range) {
        try { ch2.timeScale().setVisibleLogicalRange(range); } catch(e) {}
        try { ch3.timeScale().setVisibleLogicalRange(range); } catch(e) {}
        try { ch4.timeScale().setVisibleLogicalRange(range); } catch(e) {}
      }
    });

    ch1.subscribeCrosshairMove(function(param) {
      if (param.time && _rows) {
        var idx = -1;
        for (var i = 0; i < _rows.length; i++) { if (_rows[i].time === param.time) { idx = i; break; } }
        if (idx >= 0) {
          var r = _rows[idx], ind = _ind;
          var prev = idx > 0 ? _rows[idx-1] : r;
          var pct = ((r.c - prev.c) / prev.c * 100);
          var pctStr = (pct >= 0 ? '+' : '') + pct.toFixed(2) + '%';
          var pctCls = pct >= 0 ? '#ef5350' : '#26a69a';
          var info1 = '<div>收:<span style="color:#fff">' + f2(r.c) + '</span> 开:' + f2(r.o) + ' 高:<span style="color:#ef5350">' + f2(r.h) + '</span> 低:<span style="color:#26a69a">' + f2(r.l) + '</span> <span style="color:' + pctCls + '">涨幅∶' + pctStr + '</span></div><div>';
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
          return;
        }
      }
      if (_rows && _rows.length > 0) {
        var bars = ch1.timeScale().getBarsLogicalRange();
        if (bars && bars.from !== null && bars.to !== null) {
          var from = Math.max(0, Math.floor(bars.from));
          var to = Math.min(_rows.length - 1, Math.ceil(bars.to));
          var hi = -Infinity, lo = Infinity;
          for (var i = from; i <= to; i++) {
            if (_rows[i].h > hi) hi = _rows[i].h;
            if (_rows[i].l < lo) lo = _rows[i].l;
          }
          setInfo('info1', '<div style="color:#aaa">最高 <span style="color:#ef5350">' + f2(hi) + '</span> / 最低 <span style="color:#26a69a">' + f2(lo) + '</span></div>');
          setInfo('info2', '');
          setInfo('info3', '');
          setInfo('info4', '');
        }
      }
    });

    new ResizeObserver(function() {
      var w2 = document.getElementById('p1').clientWidth;
      ch1 && ch1.resize(w2, h1);
      ch2 && ch2.resize(w2, h2);
      ch3 && ch3.resize(w2, h3);
      ch4 && ch4.resize(w2, h4);
    }).observe(document.getElementById('p1'));

    return;
  }

  if (ch1) {
    ch1.removeSeries(cd1);
    _maWindows.forEach(function(n) { if (_maLines[n]) ch1.removeSeries(_maLines[n]); });
    ch2.removeSeries(vl);
    ch3.removeSeries(difL); ch3.removeSeries(deaL); ch3.removeSeries(macdB);
    ch4.removeSeries(kL); ch4.removeSeries(dL); ch4.removeSeries(jL);
    ch1.remove(); ch2.remove(); ch3.remove(); ch4.remove();
    ch1 = ch2 = ch3 = ch4 = null;
    cd1 = vl = difL = deaL = macdB = kL = dL = jL = null;
    _maLines = {};
    createCharts();
  }
}

// ─── 数据加载与渲染 ────────────────────────────────────────────────────────

function loadData(code, period) {
  var suffix = period === 'D' ? '' : '_' + period.toLowerCase();
  var url = _etfBaseDir + code + suffix + '.json';
  fetch(url).then(function(r) {
    if (!r.ok) throw new Error('HTTP ' + r.status + ' ' + url);
    return r.json();
  })
  .then(function(data) {
    console.log('[etf] loaded', url, 'rows:', (data.rows||[]).length, 'indKeys:', Object.keys(data.indicators||{}).slice(0,3).join(','));
    if (!data.rows || data.rows.length === 0) { setInfo('info1', '<div style="color:#f44">空数据: ' + code + '</div>'); return; }
    var ind = data.indicators || data.ind;
    _rows = data.rows;
    _ind = ind;
    console.log('[etf] render rows:', data.rows.length, 'ind:', Object.keys(ind).join(','));
    render(data.rows, ind, period);
  }).catch(function(e) {
    console.error('[etf] fetch error', url, e);
    setInfo('info1', '<div style="color:#f44">加载失败 ' + url + '<br>' + e.message + '</div>');
  });
}

function render(rows, ind, period) {
  console.log('[etf] render called rows:', rows.length, 'ind keys:', Object.keys(ind).join(','));
  var N = rows.length;
  var last = rows[N-1];
  var prev = N > 1 ? rows[N-2] : last;
  var pct = ((last.c - prev.c) / prev.c * 100);
  var pctStr = (pct >= 0 ? '+' : '') + pct.toFixed(2) + '%';
  var pctCls = pct >= 0 ? '#ef5350' : '#26a69a';

  var info1 = '<div>收:<span style="color:#fff">' + f2(last.c) + '</span> 开:' + f2(last.o) + ' 高:<span style="color:#ef5350">' + f2(last.h) + '</span> 低:<span style="color:#26a69a">' + f2(last.l) + '</span> <span style="color:' + pctCls + '">涨幅∶' + pctStr + '</span></div><div>';
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

  vl.setData(rows.map(function(r) {
    return { time: r.time, value: r.v || 0, color: r.c >= r.o ? '#ef535044' : '#26a69a44' };
  }));

  if (ind.dif) {
    difL.setData(rows.map(function(r, i) { return { time: r.time, value: ind.dif[i] }; }).filter(function(d) { return d.value != null; }));
    deaL.setData(rows.map(function(r, i) { return { time: r.time, value: ind.dea[i] }; }).filter(function(d) { return d.value != null; }));
    macdB.setData(rows.map(function(r, i) { return { time: r.time, value: ind.macd ? ind.macd[i] : null }; }).filter(function(d) { return d.value != null; }));
    setInfo('info3', '<div>DIF:<span style="color:#ff9800">' + f2(ind.dif[N-1]) + '</span> DEA:<span style="color:#00bcd4">' + f2(ind.dea[N-1]) + '</span> MACD:<span style="color:#fff">' + f2(ind.macd ? ind.macd[N-1] : null) + '</span></div>');
  }

  if (ind.K) {
    kL.setData(rows.map(function(r, i) { return { time: r.time, value: ind.K[i] }; }).filter(function(d) { return d.value != null; }));
    dL.setData(rows.map(function(r, i) { return { time: r.time, value: ind.D[i] }; }).filter(function(d) { return d.value != null; }));
    jL.setData(rows.map(function(r, i) { return { time: r.time, value: ind.J ? ind.J[i] : null }; }).filter(function(d) { return d.value != null; }));
    setInfo('info4', '<div>K:<span style="color:#ffea00">' + f2(ind.K[N-1]) + '</span> D:<span style="color:#ff9800">' + f2(ind.D[N-1]) + '</span> J:<span style="color:#e040fb">' + f2(ind.J ? ind.J[N-1] : null) + '</span></div>');
  }

  ch1.timeScale().fitContent();
}

// ─── 操作函数 ──────────────────────────────────────────────────────────────

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
  var all = document.querySelectorAll('.stk');
  var cur = document.querySelector('.stk.active');
  if (!cur) return;
  var next = all[Array.from(all).indexOf(cur) + dir];
  if (next) { next.click(); next.scrollIntoView({ block: 'nearest', behavior: 'smooth' }); }
}
function toggleSidebar() {
  var sb = document.querySelector('.sidebar');
  _sidebarCollapsed = !_sidebarCollapsed;
  sb.classList.toggle('collapsed', _sidebarCollapsed);
  document.getElementById('sidebar-arrow').innerHTML = _sidebarCollapsed ? '&#x25B6;' : '&#x25C0;';
}

function f2(v) { return v == null ? '--' : (Math.round(v * 100) / 100).toFixed(2); }
function fv(v) {
  if (v == null) return '--';
  if (v >= 100000000) return (v/100000000).toFixed(2) + '亿';
  if (v >= 10000) return (v/10000).toFixed(2) + '万';
  return v.toFixed(0);
}
function setInfo(id, html) { var el = document.getElementById(id); if (el) el.innerHTML = html; }

window.addEventListener('DOMContentLoaded', function() { loadSidebar(); });
window._searchETF = function(v) { if (window._benchData) buildSidebarETF(window._benchData, v); };
