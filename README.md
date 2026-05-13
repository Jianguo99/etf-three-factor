# etf-three-factor-v7

三因子 ETF 国家队资金监测系统 v7，用来追踪国家队（中央汇金）在宽基 ETF 上的潜在操作信号。

> v7 重大升级：`push2.eastmoney.com` 数据源长期中断，现已切换为 `akshare` 交易所官方数据接口，支持完整历史回溯。

## Skill 描述

这个 skill 支持以下能力：

- 数据获取：腾讯财经 K 线 + akshare 上交所/深交所份额数据
- 本地存储：使用 SQLite 持久化历史数据
- 三因子分析：量能概率 50% + 方向概率 20% + 份额概率 30%
- 报告输出：生成 HTML 可视化报告与 JSON 数据
- 通知发送：支持 QQ 邮箱或任意 SMTP 邮件发送

适用场景：

- 运行 ETF 三因子分析
- 查询国家队信号
- 查看每日监测报告
- 配置定时任务自动执行

## 项目结构

- `SKILL.md`：skill 入口说明
- `scripts/etf_v7_threefactor.py`：v7 主分析脚本
- `scripts/etf_data_store.py`：SQLite 数据存储模块
- `references/etf_model.md`：三因子模型详解
- `references/config.md`：配置与部署指南

## 快速开始

```bash
cd scripts
python etf_v7_threefactor.py
```

常用命令：

- `python etf_v7_threefactor.py --record`：仅采集份额数据
- `python etf_v7_threefactor.py --stats`：查看数据库状态
- `python etf_v7_threefactor.py --date 2026-04-30`：分析指定日期
- `python etf_v7_threefactor.py --send`：生成报告并发送邮件

## 三因子模型

综合概率计算方式：

```text
综合概率 = 量能概率 × 50% + 方向概率 × 20% + 份额概率 × 30%
```

其中：

- 量能因子：观察 ETF 成交量相对 20 日均量的异常放大程度
- 方向因子：结合 ETF 相对大盘表现、近期市场走势与护盘特征
- 份额因子：观察 ETF 份额变化，识别一级市场申购/赎回信号

信号分级：

- `>= 70%`：高确信
- `50% - 70%`：中等关注
- `< 50%`：正常

更多细节见 [etf_model.md](/D:/codes/etf-three-factor/references/etf_model.md)。

## 数据源

- 腾讯财经：ETF 日线 K 线与成交量数据
- akshare `fund_etf_scale_sse(date)`：上交所 ETF 份额历史
- akshare `fund_scale_daily_szse(start, end)`：深交所 ETF 份额历史

这次升级后，份额数据已经支持历史回溯，不再依赖只能读实时值的旧接口。

## 邮件配置

首次使用邮件功能前，需要配置环境变量：

```bash
export ETF_EMAIL_FROM="你的邮箱@qq.com"
export ETF_EMAIL_TO="你的收件邮箱@qq.com"
export ETF_SMTP_PASS="你的16位授权码"
```

完整配置说明见 [config.md](/D:/codes/etf-three-factor/references/config.md)。

## v6 到 v7 的变化

- 份额数据源从 `push2.eastmoney.com` 切换到 `akshare`
- 支持上交所、深交所 ETF 份额完整历史回溯
- 主脚本升级为 `scripts/etf_v7_threefactor.py`
- 邮件配置改为环境变量方案
- 工作目录与输出路径统一到新的 `~/.etf-skill` 体系

## 版权与来源

- 本项目整理自 B 站 `小贺FIRE了` 相关内容
- README 中的 skill 描述基于当前 [SKILL.md](/D:/codes/etf-three-factor/SKILL.md) 整理
- 如原作者对署名或转载方式有进一步要求，建议按原作者说明补充或调整
