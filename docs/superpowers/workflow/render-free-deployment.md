# Render 免费部署流程

本文档记录联机大富翁在 Render Free Web Service 上的部署步骤和运行限制。

## 1. 准备 GitHub 仓库

1. 确认本地测试已通过。
2. 将当前分支推送到 GitHub。
3. 在 Render 连接该 GitHub 仓库。不要在未授权时由 AI 自动推送或创建远程部署。

## 2. 使用 Render Blueprint

仓库根目录提供 `render.yaml`。在 Render Dashboard 中选择 Blueprint，并指向该仓库。

Blueprint 只创建一个 Web Service：

- `type: web`
- `runtime: python`
- `plan: free`
- `buildCommand: pip install -r requirements.txt`
- `startCommand: uvicorn server.app:app --host 0.0.0.0 --port $PORT --no-access-log --log-level warning`
- `healthCheckPath: /healthz`

Render 会提供 `$PORT`，服务必须绑定 `0.0.0.0` 和该端口。生产启动命令禁用 Uvicorn access log，并将 Uvicorn 自身日志级别调到 warning，避免 WebSocket URL 中的重连 token 出现在平台日志里。

## 3. 环境变量

`render.yaml` 固定配置：

- `PYTHON_VERSION=3.11.9`
- `APP_ENV=production`
- `LOG_LEVEL=INFO`

部署时必须在 Render 中配置：

- `ALLOWED_ORIGINS`

`ALLOWED_ORIGINS` 使用逗号分隔 Origin，例如：

```text
https://online-monopoly.onrender.com,https://your-custom-domain.example
```

未配置或配置错误会影响生产 WebSocket Origin 校验。添加自定义域名后，需要把新域名同步加入该变量。

## 4. 首次冷启动

Render Free 服务在空闲后可能休眠。首次访问或休眠后的首次访问会触发冷启动，用户可能看到短暂等待。

建议上线验收时记录：

- 首次打开 `/healthz` 的响应时间；
- 首次打开 `/` 的响应时间；
- WebSocket 首次连接耗时。

## 5. 免费休眠和状态限制

当前服务使用进程内内存保存房间状态。Render Free 服务休眠、重启或重新部署后，内存会清空，重启后房间会丢失。

用户可见处理建议：

- 提示玩家重新创建房间；
- 不承诺跨重启恢复对局；
- 不在本阶段引入数据库或 Redis。

## 6. 健康检查

Render 健康检查路径为 `/healthz`。该接口只返回服务存活状态，不依赖任何房间。

本地验证：

```powershell
$env:PORT=8000
uvicorn server.app:app --host 0.0.0.0 --port $env:PORT
```

然后访问：

- `http://127.0.0.1:8000/healthz`
- `http://127.0.0.1:8000/`

## 7. WebSocket 注意事项

生产环境会校验 WebSocket `Origin`。Render 分配域名后，必须将公开站点 Origin 写入 `ALLOWED_ORIGINS`。

浏览器客户端应使用同源地址连接 WebSocket，不要硬编码 localhost。

生产部署使用 `--no-access-log --log-level warning`，避免 Uvicorn 默认访问日志和 WebSocket 连接信息记录包含 `token=` 查询参数的 URL。

## 8. 上线验收记录

Task 18 执行时应记录：

- Render 公开 URL；
- 部署 commit；
- 冷启动时间；
- 浏览器控制台错误；
- 服务器日志；
- 已知限制，尤其是免费休眠和重启后房间会丢失。
