# -*- coding: utf-8 -*-
"""启动入口：创建 Flask app 并运行本地服务。

业务逻辑已拆入 weixin2tg/ 包（routes / services / telegram），
本文件只保留：app 实例 + 启动时诊断 + 后台清理/开浏览器线程。
"""

import threading
import time
import webbrowser

from weixin2tg import create_app
from weixin2tg.config import print_diagnostics
from weixin2tg.services.converter import find_ffmpeg
from weixin2tg.services.jobs import start_cleanup_thread

app = create_app()


def _open_browser():
    """延迟 1 秒打开浏览器（等 Flask 起来）。"""
    time.sleep(1)
    try:
        webbrowser.open("http://127.0.0.1:5000")
    except Exception:
        pass


if __name__ == "__main__":
    print_diagnostics()

    # ffmpeg 诊断
    ffmpeg = find_ffmpeg()
    if ffmpeg:
        print("FFmpeg：" + ffmpeg)
    else:
        print("警告：没有找到 FFmpeg（GIF/动态 WebP 转换将被跳过）")
    print()

    # 后台清理线程（清理过期任务与 zip）
    start_cleanup_thread()

    # 自动打开浏览器
    threading.Thread(target=_open_browser, daemon=True).start()

    # 仅监听本机
    app.run(
        host="127.0.0.1",
        port=5000,
        debug=False,
        threaded=True,
    )
