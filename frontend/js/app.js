var _selDate = 'today';

// 加载可用日期列表
function loadDates() {
  fetch('dates.json').then(function(r) { return r.json(); })
  .then(function(dates) {
    var bar = document.getElementById('dateBar');
    bar.innerHTML = '<button class="date-btn active" data-date="today">今日</button>\n';
    dates.forEach(function(d) {
      var btn = document.createElement('button');
      btn.className = 'date-btn';
      btn.dataset.date = d;
      btn.textContent = d.slice(0,4) + '-' + d.slice(4,6) + '-' + d.slice(6,8);
      btn.addEventListener('click', function() {
        document.querySelectorAll('.date-btn').forEach(function(b) { b.classList.remove('active'); });
        btn.classList.add('active');
        _selDate = d;
      });
      bar.appendChild(btn);
    });
  }).catch(function() {});
}
loadDates();

document.getElementById('etfCard').addEventListener('click', function() {
  alert('ETF功能正在开发中...');
});

function goStock() {
  var url = (_selDate === 'today') ? 'stock.html' : '../' + _selDate + '/stock.html';
  window.location.href = url;
}