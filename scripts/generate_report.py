#!/usr/bin/env python3
"""GitHub Top 200 日报：抓取、对比、生成 HTML、发送邮件。"""

from __future__ import annotations

import json
import os
import re
import smtplib
import ssl
import sys
import urllib.request
from collections import Counter
from datetime import date, datetime, timedelta
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
HISTORY_DIR = ROOT / "data" / "github-stars-history"
REPORTS_DIR = ROOT / "reports"
PROXY = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")

CATEGORY_RULES: list[tuple[str, list[str]]] = [
    ("AI / 机器学习", ["ai", "ml", "llm", "gpt", "neural", "deep-learning", "machine-learning", "transformer"]),
    ("开发工具", ["devops", "cli", "ide", "developer-tools", "productivity", "dotfiles", "terminal"]),
    ("前端 / Web", ["react", "vue", "frontend", "web", "css", "javascript", "typescript"]),
    ("后端 / 基础设施", ["kubernetes", "docker", "database", "redis", "nginx", "infrastructure", "cloud"]),
    ("安全", ["security", "pentest", "hacking", "malware", "privacy"]),
    ("教程 / 资源合集", ["awesome", "tutorial", "learn", "interview", "roadmap", "resources"]),
    ("开源应用", ["app", "self-hosted", "alternative", "desktop", "mobile"]),
]


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def github_get(url: str, retries: int = 5) -> dict[str, Any]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "github-stars-daily-report",
    }
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    opener = urllib.request.build_opener()
    if PROXY:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({"http": PROXY, "https": PROXY}))
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with opener.open(req, timeout=90) as resp:
                chunks: list[bytes] = []
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    chunks.append(chunk)
                return json.loads(b"".join(chunks).decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt + 1 < retries:
                continue
    raise RuntimeError(f"GitHub API 请求失败: {last_error}")


def fetch_top_repos(limit: int = 200) -> list[dict[str, Any]]:
    repos: list[dict[str, Any]] = []
    page = 1
    while len(repos) < limit:
        per_page = min(100, limit - len(repos))
        url = (
            "https://api.github.com/search/repositories"
            f"?q=stars:>1&sort=stars&order=desc&per_page={per_page}&page={page}"
        )
        data = github_get(url)
        items = data.get("items", [])
        if not items:
            break
        for item in items:
            repos.append(
                {
                    "rank": len(repos) + 1,
                    "full_name": item["full_name"],
                    "name": item["name"],
                    "owner": item["owner"]["login"],
                    "description": item.get("description") or "暂无描述",
                    "language": item.get("language") or "未知",
                    "stars": item.get("stargazers_count", 0),
                    "forks": item.get("forks_count", 0),
                    "topics": item.get("topics", []),
                    "html_url": item.get("html_url", ""),
                    "created_at": item.get("created_at", ""),
                    "updated_at": item.get("updated_at", ""),
                    "open_issues": item.get("open_issues_count", 0),
                }
            )
            if len(repos) >= limit:
                break
        page += 1
    return repos


def infer_category(repo: dict[str, Any]) -> str:
    text = " ".join(
        [
            repo.get("description", ""),
            repo.get("language", ""),
            " ".join(repo.get("topics", [])),
            repo.get("full_name", ""),
        ]
    ).lower()
    for name, keywords in CATEGORY_RULES:
        if any(k in text for k in keywords):
            return name
    return "其他"


def analyze_repo(repo: dict[str, Any]) -> dict[str, str]:
    desc = repo.get("description") or "暂无官方描述"
    topics = repo.get("topics") or []
    lang = repo.get("language") or "未知"
    category = infer_category(repo)

    value = (
        f"该项目属于「{category}」方向，拥有 {repo['stars']:,} Stars 和 {repo['forks']:,} Forks，"
        f"说明其在开发者社区具备较高的认可度与传播力。"
    )
    problem = (
        f"从描述来看，它主要解决：{desc}。"
        if desc != "暂无描述"
        else "项目定位需结合 README 进一步确认，但高 Star 表明其切中了广泛存在的开发者痛点。"
    )
    innovation = (
        f"核心技术栈以 {lang} 为主"
        + (f"，标签涵盖 {', '.join(topics[:6])}" if topics else "")
        + "。高关注度通常来自：问题足够普遍、上手成本低、社区运营活跃、持续迭代及时。"
    )
    insight = {
        "AI / 机器学习": "可关注其模型/Agent 架构、数据飞轮与开源商业化路径，评估是否可引入内部工具链。",
        "开发工具": "适合评估能否提升团队研发效率，优先看集成成本与维护活跃度。",
        "前端 / Web": "可借鉴其组件设计、性能优化与工程化实践，用于产品体验升级。",
        "后端 / 基础设施": "建议评估稳定性、扩展性与运维复杂度，作为架构选型参考。",
        "安全": "可用于补强安全基线、红蓝对抗或合规检查流程。",
        "教程 / 资源合集": "适合作为团队学习地图与招聘能力模型输入，降低知识检索成本。",
        "开源应用": "可评估自托管替代方案，降低 SaaS 依赖与长期成本。",
    }.get(category, "建议结合业务场景做小范围试点，用真实任务验证 ROI 后再推广。")

    return {
        "category": category,
        "value": value,
        "problem": problem,
        "innovation": innovation,
        "insight": insight,
    }


def find_snapshot(target: date) -> Path | None:
    exact = HISTORY_DIR / f"{target.isoformat()}.json"
    if exact.exists():
        return exact
    candidates = sorted(HISTORY_DIR.glob("*.json"))
    if not candidates:
        return None
    best = None
    best_delta = None
    for path in candidates:
        try:
            snap_date = datetime.strptime(path.stem, "%Y-%m-%d").date()
        except ValueError:
            continue
        delta = abs((snap_date - target).days)
        if best is None or delta < best_delta:
            best, best_delta = path, delta
    if best and best_delta is not None and best_delta <= 7:
        return best
    return None


def load_snapshot(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def compare_snapshots(current: list[dict[str, Any]], previous: list[dict[str, Any]], label: str) -> dict[str, Any]:
    prev_map = {r["full_name"]: r for r in previous}
    curr_map = {r["full_name"]: r for r in current}
    entered = [r for name, r in curr_map.items() if name not in prev_map]
    exited = [r for name, r in prev_map.items() if name not in curr_map]
    movers = []
    for name, r in curr_map.items():
        if name not in prev_map:
            continue
        delta = prev_map[name]["rank"] - r["rank"]
        if abs(delta) >= 10:
            movers.append({**r, "rank_delta": delta})
    movers.sort(key=lambda x: abs(x["rank_delta"]), reverse=True)
    star_growth = []
    for name, r in curr_map.items():
        if name not in prev_map:
            continue
        growth = r["stars"] - prev_map[name]["stars"]
        if growth > 0:
            star_growth.append({**r, "star_growth": growth})
    star_growth.sort(key=lambda x: x["star_growth"], reverse=True)
    return {
        "label": label,
        "entered": entered[:20],
        "exited": exited[:20],
        "movers": movers[:20],
        "star_growth": star_growth[:20],
        "available": True,
    }


def build_comparisons(current: list[dict[str, Any]], today: date) -> list[dict[str, Any]]:
    offsets = [
        ("昨天", 1),
        ("上周", 7),
        ("上月", 30),
        ("半年前", 180),
        ("去年", 365),
    ]
    results = []
    for label, days in offsets:
        snap_path = find_snapshot(today - timedelta(days=days))
        if not snap_path:
            results.append({"label": label, "available": False})
            continue
        previous = load_snapshot(snap_path).get("repos", [])
        results.append(compare_snapshots(current, previous, label))
    return results


def category_distribution(repos: list[dict[str, Any]]) -> Counter[str]:
    c: Counter[str] = Counter()
    for repo in repos:
        c[infer_category(repo)] += 1
    return c


def trend_analysis(repos: list[dict[str, Any]], comparisons: list[dict[str, Any]]) -> list[str]:
    dist = category_distribution(repos)
    top_cats = dist.most_common(5)
    lines = [
        f"当前 Top 200 中，领域分布前三为：{', '.join(f'{k}({v})' for k, v in top_cats[:3])}。",
        "AI / Agent / 开发工具类项目持续占据头部注意力，说明开发者仍在追逐效率提升与智能化工作流。",
        "教程与资源合集类仓库长期排名靠前，反映社区对「结构化学习路径」的刚需仍未饱和。",
    ]
    for comp in comparisons:
        if not comp.get("available"):
            continue
        entered = comp.get("entered", [])
        if entered:
            names = ", ".join(r["full_name"] for r in entered[:5])
            lines.append(f"对比{comp['label']}，新进入榜单的项目包括：{names}，显示新兴热点正在形成。")
        break
    lines.extend(
        [
            "头部格局仍偏集中：少数超级项目占据大量 Stars，但腰部项目更替活跃，创新机会存在于垂直场景。",
            "对团队的启示：优先跟踪与自身业务相邻的 10–20 个项目，小步试用，比泛泛追热点更有效。",
        ]
    )
    return lines


def esc(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def render_html(
    today: date,
    repos: list[dict[str, Any]],
    comparisons: list[dict[str, Any]],
    trends: list[str],
) -> str:
    analyses = [{**repo, **analyze_repo(repo)} for repo in repos]
    dist = category_distribution(repos)
    top5 = repos[:5]

    comp_html = []
    for comp in comparisons:
        if not comp.get("available"):
            comp_html.append(f"<h3>{esc(comp['label'])}</h3><p class='muted'>暂无历史快照数据</p>")
            continue
        comp_html.append(f"<h3>{esc(comp['label'])}</h3>")
        comp_html.append("<div class='grid'>")
        for title, key in [("新进入", "entered"), ("跌出", "exited"), ("排名大变", "movers"), ("Star 增长", "star_growth")]:
            items = comp.get(key, [])
            comp_html.append(f"<div class='card'><h4>{title}</h4><ul>")
            if not items:
                comp_html.append("<li>无显著变化</li>")
            for item in items[:8]:
                if key == "movers":
                    comp_html.append(
                        f"<li>#{item['rank']} {esc(item['full_name'])} ({item['rank_delta']:+d})</li>"
                    )
                elif key == "star_growth":
                    comp_html.append(
                        f"<li>{esc(item['full_name'])} +{item['star_growth']:,} stars</li>"
                    )
                else:
                    comp_html.append(f"<li>{esc(item['full_name'])}</li>")
            comp_html.append("</ul></div>")
        comp_html.append("</div>")

    project_html = []
    for item in analyses:
        project_html.append(
            f"""
            <section class="project" id="{esc(item['full_name'].replace('/', '-'))}">
              <h3>#{item['rank']} <a href="{esc(item['html_url'])}" target="_blank">{esc(item['full_name'])}</a>
              <span class="badge">{esc(item['category'])}</span></h3>
              <p class="meta">⭐ {item['stars']:,} · 🍴 {item['forks']:,} · {esc(item['language'])}</p>
              <p><strong>简介：</strong>{esc(item['description'])}</p>
              <p><strong>价值：</strong>{esc(item['value'])}</p>
              <p><strong>解决什么问题：</strong>{esc(item['problem'])}</p>
              <p><strong>核心创新 / 为何受关注：</strong>{esc(item['innovation'])}</p>
              <p><strong>对我们的启发：</strong>{esc(item['insight'])}</p>
            </section>
            """
        )

    trend_html = "".join(f"<li>{esc(line)}</li>" for line in trends)
    dist_html = "".join(f"<li>{esc(k)}：{v} 个</li>" for k, v in dist.most_common())

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>GitHub 热门项目日报 - {today.isoformat()}</title>
  <style>
    :root {{ --bg:#0b1020; --card:#141b2d; --text:#e8ecf8; --muted:#9aa7c7; --accent:#6ea8fe; --border:#24304d; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; background:var(--bg); color:var(--text); line-height:1.6; }}
    .wrap {{ max-width:1100px; margin:0 auto; padding:32px 20px 80px; }}
    h1 {{ font-size:2rem; margin-bottom:8px; }}
    h2 {{ margin-top:40px; border-bottom:1px solid var(--border); padding-bottom:8px; }}
    h3 {{ margin-top:24px; }}
    .muted {{ color:var(--muted); }}
    .summary {{ background:var(--card); border:1px solid var(--border); border-radius:12px; padding:20px; }}
    .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:16px; }}
    .card {{ background:var(--card); border:1px solid var(--border); border-radius:12px; padding:16px; }}
    .project {{ background:var(--card); border:1px solid var(--border); border-radius:12px; padding:18px; margin:16px 0; }}
    .meta {{ color:var(--muted); }}
    .badge {{ display:inline-block; margin-left:8px; padding:2px 8px; border-radius:999px; background:#1f2a44; color:var(--accent); font-size:12px; }}
    a {{ color:var(--accent); text-decoration:none; }}
    ul {{ padding-left:20px; }}
    .toc a {{ display:block; margin:4px 0; }}
  </style>
</head>
<body>
  <div class="wrap">
    <h1>GitHub 热门项目日报</h1>
    <p class="muted">生成日期：{today.isoformat()} · Top 200 by Stars</p>

    <section class="summary">
      <h2>执行摘要</h2>
      <p>今日 Top 5：{', '.join(esc(r['full_name']) for r in top5)}</p>
      <p>本报告覆盖 200 个 GitHub 最受关注项目，包含逐项目中文解读、历史榜单对比与行业趋势分析。</p>
    </section>

    <h2>榜单变化对比</h2>
    {''.join(comp_html)}

    <h2>行业趋势解读</h2>
    <ul>{trend_html}</ul>

    <h2>领域分布</h2>
    <ul>{dist_html}</ul>

    <h2>逐项目详情</h2>
    <div class="toc muted">共 200 个项目，按 Star 排名排序</div>
    {''.join(project_html)}
  </div>
</body>
</html>
"""


def send_email(subject: str, body: str, attachment_path: Path, to_addr: str) -> None:
    host = os.environ.get("SMTP_HOST", "smtp.163.com")
    port = int(os.environ.get("SMTP_PORT", "465"))
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASS")
    from_addr = os.environ.get("SMTP_FROM") or user
    if not all([user, password, from_addr]):
        raise RuntimeError("SMTP 凭据未配置：需要 SMTP_USER、SMTP_PASS、SMTP_FROM")

    msg = MIMEMultipart()
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg.attach(MIMEText(body, "plain", "utf-8"))

    with open(attachment_path, "rb") as f:
        part = MIMEApplication(f.read(), Name=attachment_path.name)
        part["Content-Disposition"] = f'attachment; filename="{attachment_path.name}"'
        msg.attach(part)

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(host, port, context=context, timeout=30) as server:
        server.login(user, password)
        server.sendmail(from_addr, [to_addr], msg.as_string())


def main() -> int:
    load_dotenv(ROOT / ".env")
    today = date.today()
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    print("正在抓取 GitHub Top 200 ...")
    repos = fetch_top_repos(200)
    print(f"已获取 {len(repos)} 个项目")

    snapshot = {
        "date": today.isoformat(),
        "generated_at": datetime.now().isoformat(),
        "repos": repos,
    }
    snap_path = HISTORY_DIR / f"{today.isoformat()}.json"
    snap_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"快照已保存: {snap_path}")

    comparisons = build_comparisons(repos, today)
    trends = trend_analysis(repos, comparisons)
    html = render_html(today, repos, comparisons, trends)

    report_path = REPORTS_DIR / f"github-stars-report-{today.isoformat()}.html"
    report_path.write_text(html, encoding="utf-8")
    print(f"报告已生成: {report_path}")

    to_addr = os.environ.get("REPORT_TO", "qylybest@163.com")
    subject = f"GitHub 热门项目日报 - {today.isoformat()}"
    body = (
        f"GitHub 热门项目日报已生成。\n\n"
        f"今日 Top 5: {', '.join(r['full_name'] for r in repos[:5])}\n"
        f"趋势要点: {trends[0]}\n\n"
        f"完整报告见附件。"
    )

    try:
        send_email(subject, body, report_path, to_addr)
        print(f"邮件已发送至 {to_addr}")
    except Exception as e:
        print(f"邮件发送失败: {e}", file=sys.stderr)
        print("报告文件已本地生成，可手动查收或检查 SMTP 配置。", file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
