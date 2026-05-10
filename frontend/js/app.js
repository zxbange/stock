var _selDate = 'today';

var sel = document.getElementById('dateSelect');
sel.addEventListener('change', function() {
  _selDate = sel.value;
});
document.getElementById('etfCard').addEventListener('click', function() {
  alert('ETF功能正在开发中...');
});

function goStock() {
  var url = _selDate === 'today' ? 'stock.html?v=210531' : 'stock.html?date=' + _selDate + '&v=210531';
  window.location.href = url;
}

// 加载历史日期到下拉菜单
fetch('/dates.json').then(function(r) { return r.json(); })
.then(function(dates) {
  dates.forEach(function(d) {
    var opt = document.createElement('option');
    opt.value = d;
    opt.textContent = d.slice(0,4) + '-' + d.slice(4,6) + '-' + d.slice(6,8);
    sel.appendChild(opt);
  });
}).catch(function() {});