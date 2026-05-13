# ETF三因子系统 — 配置与部署指南

---

## 🔧 环境依赖

```bash
# 系统要求
Python 3.7+
macOS / Linux（Windows未测试）

# 无需额外pip包（全部标准库）
# 使用: json, urllib, sqlite3, smtplib, email, argparse
```

---

## 📧 邮件配置

### QQ邮箱授权码获取
1. 登录QQ邮箱 → 设置 → 账户
2. 找到「POP3/IMAP/SMTP/Exchange/CardDAV/CalDAV服务」
3. 开启SMTP服务 → 获取授权码
4. 配置环境变量：

```bash
# 方式1: 临时（当前终端有效）
export QQMAIL_AUTH_CODE="你的16位授权码"

# 方式2: 永久（写入 shell 配置文件）
echo 'export QQMAIL_AUTH_CODE="你的16位授权码"' >> ~/.zshrc
source ~/.zshrc
```

### 邮件参数（脚本内置）

| 参数 | 值 |
|------|-----|
| SMTP服务器 | smtp.qq.com:465 |
| 发件邮箱 | 28289062@qq.com |
| 收件邮箱 | 28289062@qq.com |
| 加密方式 | SSL |

---

## 🗄️ 数据库说明

- 文件位置：`~/.qclaw/workspace/etf_history.db`
- 表：`etf_daily` — 每只ETF每天一条记录
- 引擎：SQLite3（无需安装数据库软件）

### 表字段

```
date        TEXT    日期 YYYY-MM-DD
code        TEXT    ETF代码
name        TEXT    ETF名称
idx_name    TEXT    跟踪指数
volume      REAL    成交量(万手)
volume_ma20 REAL    20日均量(万手)
volume_ratio REAL   倍量(vr)
shares_yi   REAL    份额(亿份)
shares_delta_yi REAL 份额日变(亿份)
vol_prob    REAL    量能概率(%)
dir_prob    REAL    方向概率(%)
share_prob  REAL    份额概率(%)
composite_prob REAL 综合概率(%)
signal_level TEXT   信号级别(HIGH/MID/LOW)
```

---

## 🔗 API数据源

| 数据 | API | 格式 | 限制 |
|------|-----|------|------|
| K线（价/量） | `web.ifzq.gtimg.cn` | JSON | 可回溯60天 |
| 实时份额 | `push2.eastmoney.com` | JSON | **仅当天实时**，周末不返回 |

### 腾讯财经API示例
```
http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=sh510300,day,,,60,qfq
```

### 东方财富push2 API示例
```
https://push2.eastmoney.com/api/qt/stock/get?secid=1.510300&fields=f43,f57,f58,f116
```
- f43: 当前价 | f57: 代码 | f58: 名称 | f116: 总市值

### 份额数据补充来源（可替代push2）

上交所官网每日收盘后公布所有ETF份额：
- **优点**：最及时准确，历史可查
- **缺点**：HTML页面需爬虫解析，不如API友好

---

## ⏰ 定时任务部署

### 建议方案
```
工作日 16:30 → 收盘后采集份额 + 分析
工作日 09:30 → 开盘前发送昨日报告
```

### 创建定时任务（通过QClaw cron）

```bash
openclaw cron add
```

然后在对话中描述：
> 每周一到周五 16:30 执行：运行 etf_v6_threefactor.py --send，生成三因子报告并发送邮件到 28289062@qq.com

---

## 📁 文件清单

```
~/.qclaw/
├── skills/etf-three-factor/        # 本skill目录
│   ├── SKILL.md
│   ├── scripts/
│   │   ├── etf_v6_threefactor.py   # 主分析脚本
│   │   └── etf_data_store.py       # 数据存储模块
│   └── references/
│       ├── etf_model.md            # 三因子模型详解
│       └── config.md               # 本文件（配置指南）
│
└── workspace/
    ├── etf_v6_threefactor.py       # 原始脚本（workspace副本）
    ├── etf_data_store.py           # 原始存储模块
    ├── etf_history.db              # SQLite数据库
    ├── etf_shares_history.json     # 份额JSON历史
    ├── ETF三因子分析-终版.html     # 实时输出
    └── ETF三因子分析-终版.json     # 实时输出
```

---

## 🔄 升级指南

当需要升级监控ETF列表时，修改 `scripts/etf_v6_threefactor.py` 中的 `ETFS` 字典：

```python
ETFS = {
    "510300": {"n": "华泰柏瑞沪深300ETF", "idx": "沪深300", "p": 5},
    # 新增ETF ↓
    "588000": {"n": "华夏科创50ETF",     "idx": "科创50",  "p": 3},
}
```

同时需要在 `PUSH2_MKT` 中注册代码：`"588000": "1"`（上海=1，深圳=0）