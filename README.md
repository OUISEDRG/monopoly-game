# 大富翁单机手机版

这是旧单机版的手机 PWA 入口。它不需要 Python 服务端，所有规则仍在 `index.html` 内运行。

## 本地运行

在 `offline/mobile/` 目录启动任意静态服务器：

```powershell
python -m http.server 8787
```

然后访问：

```text
http://127.0.0.1:8787/
```

首次加载后，浏览器会注册 Service Worker。支持 PWA 的手机浏览器可把它添加到主屏幕。

## 后续 APK 封装

后续如需 Android APK，可以把本目录作为 Capacitor 的 `webDir`。本目录已经包含运行所需 HTML、Service Worker、manifest、字体和图标。
