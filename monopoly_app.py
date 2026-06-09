# -*- coding: utf-8 -*-
"""Monopoly mini-game launcher.

When packaged with PyInstaller, include ``monopoly.html`` with ``--add-data``.
"""

import http.server
import socket
import webbrowser
import threading
import sys
import os

def resource_path(relative_path):
    """Return an absolute resource path, including PyInstaller bundles."""
    try:
        base_path = sys._MEIPASS  # PyInstaller 临时目录
    except Exception:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)


def get_free_port():
    """Return an available local port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        return s.getsockname()[1]


# 预加载 HTML 内容
_HTML_PATH = resource_path('monopoly.html')
try:
    with open(_HTML_PATH, 'r', encoding='utf-8') as f:
        HTML_CONTENT = f.read()
except FileNotFoundError:
    HTML_CONTENT = """
    <!DOCTYPE html>
    <html><head><meta charset="UTF-8"><title>错误</title></head>
    <body style="background:#1a1a2e;color:#e8d5b7;display:flex;align-items:center;justify-content:center;height:100vh;font-family:sans-serif;">
    <div style="text-align:center;">
    <h1 style="color:#e74c3c;">启动错误</h1>
    <p>无法找到游戏资源文件 monopoly.html</p>
    <p>请重新安装游戏。</p>
    </div></body></html>
    """


class MonopolyHandler(http.server.SimpleHTTPRequestHandler):
    """自定义HTTP请求处理器"""
    def do_GET(self):
        if self.path == '/' or self.path == '/monopoly.html':
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(HTML_CONTENT.encode('utf-8'))
        elif self.path == '/favicon.ico':
            self.send_response(204)
            self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # 静默日志


def main():
    port = get_free_port()
    server = http.server.HTTPServer(('127.0.0.1', port), MonopolyHandler)

    print(f"大富翁游戏已启动！")
    print(f"如果浏览器未自动打开，请手动访问: http://127.0.0.1:{port}")
    print("关闭此窗口按 Ctrl+C 退出游戏。")

    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    webbrowser.open(f'http://127.0.0.1:{port}')

    try:
        input("按 Enter 退出...")
    except (EOFError, KeyboardInterrupt):
        pass

    server.shutdown()
    server.server_close()
    print("游戏已退出。")


if __name__ == '__main__':
    main()
