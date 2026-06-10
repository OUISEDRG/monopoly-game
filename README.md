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

## 双 AI 协作

每轮工作开始前，先阅读：

1. `.agents/skills/ai-handoff-coordinator/SKILL.md`
2. `.agents/skills/cleanup-archive-coordinator/SKILL.md`
3. `docs/superpowers/交接记录/` 中唯一的最新交接报告

完成工作后必须先清理临时文件、归档正式产物并生成清理归档记录，
再创建新的时间戳交接报告。新报告核验后删除旧交接报告，只保留最新一份。
