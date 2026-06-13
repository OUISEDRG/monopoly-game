# 大富翁小游戏

一个使用单页 HTML 和 Python 本地服务器运行的大富翁桌游项目。

## 运行游戏

Windows 下双击 `run.bat`，或在项目根目录执行：

```powershell
python monopoly_app.py
```

启动器会选择一个可用的本地端口并自动打开浏览器。

## 项目结构

```text
.
├── monopoly.html          # 游戏界面、规则和主要逻辑
├── monopoly_app.py        # 本地 HTTP 启动器
├── run.bat                # Windows 快速启动入口
├── tests/                 # Node.js 自动化测试
├── docs/superpowers/
│   ├── specs/             # 设计规范
│   ├── plans/             # 实施计划
│   ├── changelogs/        # 功能变更记录
│   ├── archives/           # 每项任务的清理归档记录
│   ├── workflow/          # AI 协作流程
│   └── 交接记录/          # 仅保留最新 AI 工作交接报告
└── .agents/skills/        # 项目共享 AI 技能
```

根目录中的 `monopoly_review.md` 和 `桌游版大富翁经济系统与规则.md`
分别记录项目评审结论和完整游戏规则。

## 自动化检查

运行全部 JavaScript 测试：

```powershell
node --test tests/*.mjs
```

检查 Python 启动器：

```powershell
python -m py_compile monopoly_app.py
```

修改 `monopoly.html` 中的 JavaScript 后，还应提取内联脚本并运行
`node --check`，同时执行 `git diff --check`。

## Render 免费部署

联机版服务可通过仓库根目录的 `render.yaml` 部署到 Render Free Web Service。

部署入口：

```text
render.yaml
docs/superpowers/workflow/render-free-deployment.md
```

关键配置：

- Build Command: `pip install -r requirements.txt`
- Start Command: `uvicorn server.app:app --host 0.0.0.0 --port $PORT --no-access-log --log-level warning`
- Health Check Path: `/healthz`
- Required environment: `APP_ENV=production`
- Required Render setting: `ALLOWED_ORIGINS`

`ALLOWED_ORIGINS` 必须配置为 Render 分配域名或自定义域名的 Origin，例如：

```text
https://online-monopoly.onrender.com
```

旧单机入口仍保留，可继续使用 `python monopoly_app.py` 本地运行。

生产部署禁用 Uvicorn access log，并将 Uvicorn 自身日志级别调到 warning，避免 WebSocket 重连 token 出现在平台日志中。

## 联机版发布验收

联机版验收记录位于：

```text
docs/superpowers/changelogs/2026-06-11-online-multiplayer-changelog.md
```

关键检查包括：

```powershell
python -m pytest tests/integration/test_full_game.py -q
python -m pytest tests/server/test_deployment_config.py -q
python -m pytest -q
node --test tests/*.mjs
```

完整公网验收仍需要真实 Render URL，用于记录冷启动、跨网络加入同房间、浏览器控制台和服务器日志。

## 双 AI 协作

每轮工作开始前，先阅读：

1. `.agents/skills/ai-handoff-coordinator/SKILL.md`
2. `.agents/skills/cleanup-archive-coordinator/SKILL.md`
3. `docs/superpowers/交接记录/` 中唯一的最新交接报告

完成工作后必须先清理临时文件、归档正式产物并生成清理归档记录，
再创建新的时间戳交接报告。新报告核验后删除旧交接报告，只保留最新一份。
