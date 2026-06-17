# GitHub 热门项目日报

每日抓取 GitHub star 数 Top 200 项目，生成中文 HTML 分析报告。

## 目录结构

- `data/github-stars-history/` — 每日榜单 JSON 快照（用于历史对比）
- `reports/` — 生成的 HTML 报告

## 关联自动化

Cursor Automation「GitHub 热门项目日报」，每天 10:00 运行。

## 邮件发送

脚本会优先生成本地 JSON 快照与 HTML 报告。未配置 `REPORT_TO` 时会跳过邮件发送；如需让邮件发送失败时返回非零退出码，可设置 `REPORT_FAIL_ON_EMAIL_ERROR=true`。
