# ⚙️ ETF三因子系统 v7 — 配置与部署指南

---

## 🔧 环境依赖

```bash
# 系统要求
Python 3.7+
macOS / Linux

# Python 包
pip3 install akshare          # 交易所ETF份额数据（必需）
# 其余为标准库：json, urllib, sqlite3, smtplib, email, argparse
```

---

## 📧 邮件配置（必读）

### Step 1：配置你的邮箱

邮件功能依赖环境变量，**使用前必须配置**：

```bash
# ===== 必填项 =====
# 你的邮箱地址（发件人和收件人，可以相同）
export ETF_EMAIL_FROM="你的邮箱@qq.com"
export ETF_EMAIL_TO="你的收件邮箱@qq.com"

# SMTP认证密码（QQ邮箱用16位授权码，在QQ邮箱网页设置中获取）
export ETF_SMTP_PASS="你的授权码"

# ===== 可选项 =====
# 默认使用QQ邮箱SMTP，如需其他邮箱服务：
# export ETF_SMTP_HOST="smtp.qq.com"
# export ETF_SMTP_PORT="465"

# 永久写入 ~/.zshrc（推荐）
cat >> ~/.zshrc << 'EOF'
export ETF_EMAIL_FROM="你的邮箱@qq.com"
export ETF_EMAIL_TO="你的收件邮箱@qq.com"
export ETF_SMTP_PASS="你的授权码"
EOF
source ~/.zshrc
```

### 邮件参数默认值

| 参数 | 默认值 | 说明 |
|------|--------|------|
| SMTP服务器 | smtp.qq.com:465 | 可改为其他邮件服务商 |
| 发件邮箱 | `ETF_EMAIL_FROM` | 必填 |
| 收件邮箱 | `ETF_EMAIL_TO` | 必填 |
| 认证密码 | `ETF_SMTP_PASS` | 必填，QQ邮箱用授权码 |

---

## 🗄️ 数据库说明

### 基本信息
- 文件位置：`~/.etf-skill/workspace/etf_history.db`
- 引擎：SQLite3（无需安装数据库）
- 表名：`etf_daily` — 每只ETF每天一条记录

### 表字段

| 字段 | 类型 | 说明 |
|------|------|------|
| date | TEXT | 日期 YYYY-MM-DD |
| code | TEXT | ETF代码 |
| name | TEXT | ETF名称 |
| idx_name | TEXT | 跟踪指数 |
| close_price | REAL | 收盘价 |
| change_pct | REAL | 涨跌幅(%) |
| volume | REAL | 成交量(万手) |
| volume_ma20 | REAL | 20日均量(万手) |
| volume_ratio | REAL | 倍量(vr) |
| shares_yi | REAL | 份额(亿份) |
| shares_delta_yi | REAL | 份额日变(亿份) |
| shares_delta_pct | REAL | 份额日变(%) |
| vol_prob | REAL | 量能概率(%) |
| dir_prob | REAL | 方向概率(%) |
| share_prob | REAL | 份额概率(%) |
| composite_prob | REAL | 综合概率(%) |
| idx_chg | REAL | 沪深300涨跌幅(%) |
| signal_level | TEXT | 信号级别(HIGH/MID/LOW) |

---

## 🔗 API数据源（v7）

### 1. K线行情 — 腾讯财经

```
http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=sh510300,day,,,60,qfq
```

| 属性 | 值 |
|------|-----|
| 数据 | 日线OHLC + 成交量 |
| 历史 | 可回溯60天 |
| 频率 | 每日收盘后更新 |
| 费用 | 免费，无需Key |

### 2. 上交所ETF份额 — akshare

```python
import akshare as ak

df = ak.fund_etf_scale_sse(date='20260512')
# 返回全部上交所ETF当日份额
# df.columns: [序号, 基金代码, 基金简称, ETF类型, 统计日期, 基金份额]
```

| 属性 | 值 |
|------|-----|
| 数据 | ETF总份额（份） |
| 历史 | ✅ 完整历史 |
| 更新 | 盘后约19:00 |
| 费用 | 免费 |

### 3. 深交所ETF份额 — akshare

```python
import akshare as ak

df = ak.fund_scale_daily_szse(start_date='20260506', end_date='20260512', symbol='ETF')
# 返回指定日期范围内全部深交所ETF份额
# df.columns: [日期, 基金代码, 基金简称, 基金份额]
```

| 属性 | 值 |
|------|-----|
| 数据 | ETF总份额（份） |
| 历史 | ✅ 完整历史（支持日期范围） |
| 更新 | 盘后约19:00 |
| 费用 | 免费 |

---

## ⏰ 定时任务部署

### 建议方案

| 场景 | 时间 | 命令 |
|------|------|------|
| 日报（收盘后） | 工作日 16:30 | `python3 etf_v7_threefactor.py --send` |
| 仅记录份额 | 工作日 16:00 | `python3 etf_v7_threefactor.py --record` |

### 创建定时任务（推荐：收盘后完整分析）

```bash
openclaw cron add
```

配置：
```yaml
name: "ETF三因子日报-v7·16:30"
schedule: "30 16 * * 1-5"  # 周一至周五 16:30（Asia/Shanghai）
sessionTarget: isolated
payload:
  kind: agentTurn
  message: |
    运行 ETF v7 三因子分析（完整流程）:
    cd ~/.etf-skill/scripts
    python3 etf_v7_threefactor.py --send
  timeoutSeconds: 180
```

---

## 📁 文件清单

```
~/.etf-skill/
├── scripts/                         # 主脚本目录
│   ├── etf_v7_threefactor.py        # 主分析脚本（一键流水线）
│   └── etf_data_store.py            # SQLite数据存储模块
└── workspace/
    ├── etf_history.db                # SQLite数据库
    ├── etf_shares_history.json       # 份额JSON历史（自动维护）
    ├── ETF三因子分析-v7.html         # HTML报告
    └── ETF三因子分析-v7.json         # JSON数据

# Skill说明文件（与本文件同级目录）
SKILL.md              # 技能说明
references/
  ├── etf_model.md    # 三因子模型详解
  └── config.md        # 本文件（配置指南）
```

---

## 🔄 自定义监控ETF

修改 `scripts/etf_v7_threefactor.py` 中的 `ETFS` 字典：

```python
ETFS = {
    "510300": {"n": "华泰柏瑞沪深300ETF", "idx": "沪深300", "p": 5},
    # ↓ 新增ETF示例
    "588000": {"n": "华夏科创50ETF",     "idx": "科创50",  "p": 3},
}
```

新增的沪深ETF（51/56开头）由 akshare `fund_etf_scale_sse` 覆盖，深圳ETF（159开头）由 `fund_scale_daily_szse` 覆盖。

---

## 🛠️ 故障排查

### akshare 导入报错
```bash
pip3 install akshare --upgrade
```

### 份额数据为空（周末/假日）
正常现象。非交易日无份额数据，脚本自动回退到最近交易日。

### HTML文件过大
每次运行覆盖同一HTML文件。如需保留历史报告，复制到带日期的文件名。

### 首次运行
- 自动从akshare回溯最近20个交易日份额数据
- 后续每次运行递增1天（增量采集）
- 约40~50秒完成首次回溯

### 邮件发送失败
1. 确认 `ETF_EMAIL_FROM` / `ETF_EMAIL_TO` / `ETF_SMTP_PASS` 已正确设置
2. 确认QQ邮箱SMTP服务已开启
3. 确认授权码是**最新**获取的（16位）

```bash
# 测试环境变量
echo $ETF_EMAIL_FROM
echo $ETF_SMTP_PASS
```
