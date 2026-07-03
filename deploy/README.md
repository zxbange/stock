# Deploy / Nginx 配置

## nginx_stock.conf
每日选股项目的 nginx 站点配置。

- **监听端口**: `8080`
- **根目录**: `/home/bange/stock/frontend`
- **公网访问**: `http://119.28.106.127:8080/`
- **服务对象**: stock.html / market.html / etf.html / weipan.html / 行情监控等所有前端页面，以及 daily_result 历史归档和 today/ 当日结果

### 部署方式
```bash
# 复制到 nginx 站点目录
sudo cp nginx_stock.conf /etc/nginx/sites-available/kline

# 创建软链启用
sudo ln -sf /etc/nginx/sites-available/kline /etc/nginx/sites-enabled/kline

# 测试并重载
sudo nginx -t && sudo systemctl reload nginx
```

### 主要路由
- `/` → `frontend/index.html`
- `/stock.html` `/market.html` `/etf.html` `/weipan.html` `/market_summary.html` `/weipan_images.html` → 前端页面（强制不缓存）
- `/today/` → `/home/bange/stock/daily_result/today/`  当日选股结果
- `/dates.json` → 历史日期列表
- `/{YYYYMMDD}/` → 按日期归档的选股结果（302 跳转到 stock.html）
- `/data_kline/` `/data_etf/` `/data/market_crowding.csv` `/data/weipan_metrics.csv` → 数据文件
