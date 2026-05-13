# etf-three-factor

三因子 ETF 监控系统，用来追踪国家队（中央汇金）在宽基 ETF 上的潜在操作信号。

## Skill 描述

这个 skill 支持以下能力：

- 数据获取：腾讯财经行情 + 东方财富份额数据
- 本地存储：使用 SQLite 持久化历史数据
- 三因子分析：量能概率 50% + 方向概率 20% + 份额概率 30%
- 报告输出：生成 HTML 可视化报告与 JSON 数据
- 通知发送：支持邮件发送分析结果

适用场景：

- 运行 ETF 三因子分析
- 查询国家队信号
- 查看每日监测报告
- 配置定时任务自动执行

## 项目结构

- `SKILL.md`：skill 入口说明
- `scripts/etf_v6_threefactor.py`：主分析脚本
- `scripts/etf_data_store.py`：SQLite 数据存储模块
- `references/etf_model.md`：三因子模型详解
- `references/config.md`：配置与部署指南

## 三因子模型

综合概率计算方式：

```text
综合概率 = 量能概率 × 50% + 方向概率 × 20% + 份额概率 × 30%
```

其中：

- 量能因子：观察 ETF 成交量相对 20 日均量的异常放大程度
- 方向因子：结合 ETF 相对大盘表现、近期市场走势与护盘特征
- 份额因子：观察 ETF 份额变化，识别一级市场申购/赎回信号

更多细节见 [references/etf_model.md](/D:/codes/etf-three-factor/references/etf_model.md)。

## 使用方式

```bash
cd scripts
python etf_v6_threefactor.py
```

常用命令：

- `python etf_v6_threefactor.py --record`：仅采集当日份额
- `python etf_v6_threefactor.py --stats`：查看数据库状态
- `python etf_v6_threefactor.py --date 2026-04-30`：分析指定日期
- `python etf_v6_threefactor.py --send`：生成报告并发送邮件

## 版权与来源

- 本项目整理自 B 站 `小贺FIRE了` 相关内容
- README 中的 skill 描述基于当前 `SKILL.md` 整理
- 如原作者对署名或转载方式有进一步要求，建议按原作者说明补充或调整
