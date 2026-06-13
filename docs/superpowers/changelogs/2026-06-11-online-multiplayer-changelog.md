# 联机大富翁发布验收变更记录

## 范围

本记录汇总 2026-06-11 在线多人实施计划的发布验收状态，覆盖从大厅创建到完整对局结束、浏览器验收、Render 部署准备、安全边界和旧单机入口保留。

## 已完成能力

- 多人大厅：支持昵称创建房间、加入房间、准备、房主开始。
- WebSocket 同步：连接认证、初始快照、状态广播、断线重连和版本化命令结果。
- 服务端权威规则：掷骰、购买、拍卖、地产管理、交易、债务、破产和游戏结束均在服务端执行。
- 完整对局：新增 `tests/integration/test_full_game.py`，覆盖从房间创建到仅剩一名玩家并进入 `GAME_OVER`。
- 安全边界：生产环境 WebSocket Origin 校验、命令限流、消息大小限制、日志脱敏和部署命令日志抑制。
- Render 准备：新增 `render.yaml` 和 `docs/superpowers/workflow/render-free-deployment.md`。

## 验收证据

- `python -m pytest tests/integration/test_full_game.py -q`
- `python -m pytest tests/server/test_deployment_config.py -q`
- `python -m pytest -q`
- `node --test tests/*.mjs`
- `python -m py_compile monopoly_app.py server/app.py server/room_manager.py server/transport/websocket.py server/security.py`
- `git diff --check`

## 浏览器验收

本地浏览器验收使用既有脚本：

- `tests/browser/online_playwright_check.py`
- `tests/browser/online_smoke.spec.mjs`

验收重点：

- 桌面宽度可创建和加入房间；
- 移动端宽度无明显横向溢出；
- 基础大厅和联机棋盘 UI 可渲染；
- 浏览器控制台无未处理错误。

## Render 验收

当前仓库只准备 Render Blueprint，不自动推送或创建真实服务。真实上线时仍需记录：

- Render 公开 URL；
- 部署 commit；
- 首次冷启动时间；
- 浏览器控制台错误；
- 服务器日志；
- 免费休眠和重启后房间会丢失的限制。

## 旧单机入口

旧单机入口继续保留：

- `monopoly.html`
- `monopoly_app.py`
- `run.bat`

删除旧入口需要用户另行批准。

## 已知限制

- 当前房间状态保存在单进程内存中，Render 休眠、重启或重新部署后房间会丢失。
- HTTP 创建/加入接口按 IP 轻量限流仍可作为后续安全收尾任务补充。
- 未在本地自动执行真实跨网络双设备验收；该项需要真实 Render URL 或局域网/公网环境。
