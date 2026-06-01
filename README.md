# Auto投放 - Facebook & Google Ads 自动化管理系统

自动管理 Facebook 和 Google Ads 投放，包含预算控制切换、素材轮换、定时报表推送。

## 功能

- **预算自动优化**: 基于 CPI + ROAS 双指标，在 Facebook 和 Google Ads 之间自动分配预算
- **素材自动轮换**: 素材表现差（CPI 连续超标）时自动切换到下一个素材
- **每日预算上限**: 全局日消耗控制，超上限自动暂停所有 Campaign
- **定时报表**: 每小时出小时报，每天出日报
- **消息推送**: 报表自动推送到飞书 Webhook 和邮箱（可配置）
- **Web 仪表盘**: 实时查看投放数据、历史报表

## 快速开始

### 本地运行

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

访问 http://localhost:8000

### Docker 部署

```bash
docker compose up -d
```

## 配置

编辑 `config.yaml`:

```yaml
app:
  daily_spend_cap: 10000.0     # 每日投放总额上限
  default_cpi_cap: 2.5         # 默认 CPI 上限
  default_roas_threshold: 1.2  # 默认 ROAS 阈值
  creative_fail_hours: 2       # 连续几小时 CPI 超标后换素材
  budget_shift_ratio: 0.7      # 优势平台获得的预算比例
  use_mock: true               # true=模拟数据, false=接真实API

notifications:
  feishu:
    enabled: true
    webhook_url: "https://open.feishu.cn/open-apis/bot/v2/hook/xxx"
  email:
    enabled: false
    smtp_host: "smtp.example.com"
    smtp_port: 465
    smtp_user: ""
    smtp_password: ""
    recipients: ["ops@example.com"]
```

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/campaigns` | 获取所有 Campaign |
| POST | `/api/campaigns` | 创建 Campaign（含素材） |
| PATCH | `/api/campaigns/{id}` | 更新 Campaign 配置 |
| GET | `/api/reports?type=hourly&date=2026-06-01` | 查询报表 |
| POST | `/api/optimize/trigger` | 手动触发优化周期 |
| GET | `/api/stats/today` | 今日实时统计 |
| POST | `/api/seed-demo` | 导入示例数据 |

## Web 页面

| 路径 | 说明 |
|------|------|
| `/` | 仪表盘首页 |
| `/reports/hourly` | 小时报列表 |
| `/reports/daily` | 日报列表 |
| `/reports/{id}` | 报告详情 |

## 预算切换逻辑

```
每小时执行一次:
1. 获取两个平台所有活跃 Campaign 的 CPI 和 ROAS 数据
2. 判断平台健康状态: CPI <= 上限 且 ROAS >= 阈值 = 健康
3. 决策:
   - 两边都健康 / 都不好 → 预算 50/50 平分
   - 只有 FB 健康 → 70% 给 FB, 30% 给 Google
   - 只有 Google 健康 → 70% 给 Google, 30% 给 FB
   - 日消耗达到上限 → 暂停所有 Campaign
4. 检查素材: CPI 连续 N 小时超标 → 切换到下一个素材
```

## 项目结构

```
app/
├── main.py              # FastAPI 入口
├── config.py            # 配置管理
├── database.py          # 数据库连接
├── models.py            # ORM 模型
├── schemas.py           # Pydantic 数据模型
├── scheduler.py         # 定时任务
├── services/
│   ├── ads_interface.py     # 广告平台抽象接口
│   ├── mock_facebook.py     # Facebook Mock 客户端
│   ├── mock_google.py       # Google Mock 客户端
│   ├── budget_optimizer.py  # 预算优化引擎
│   ├── campaign_manager.py  # 素材轮换管理
│   ├── report_builder.py    # 报表生成
│   └── notifier.py          # 飞书/邮件推送
├── routers/
│   ├── api.py           # JSON API
│   └── dashboard.py     # Web 页面
├── templates/           # Jinja2 模板
└── static/              # CSS 样式
```

## 接入真实 API

1. 实现 `AdsClient` 接口（参考 `mock_facebook.py`）
2. 在 `scheduler.py` 的 `get_clients()` 中注册真实客户端
3. 将 `config.yaml` 中 `use_mock` 设为 `false`
