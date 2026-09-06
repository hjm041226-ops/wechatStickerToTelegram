# -*- coding: utf-8 -*-
"""全局配置：路径常量与环境变量读取。

路径说明：
- BASE_DIR：项目根目录（本文件位于 <根>/weixin2tg/config.py）
- WORK_DIR：运行产物目录；可用环境变量 WX2TG_WORK_DIR 覆盖（测试隔离用）
- PREVIEW_DIR：扫描后的网格预览图（随 WORK_DIR 变化）
"""

import os
from pathlib import Path

# 项目根目录
BASE_DIR = str(Path(__file__).resolve().parent.parent)

# Flask 静态目录（前端 css/js 所在，必须是真实存在的目录）
STATIC_FOLDER = os.path.join(BASE_DIR, "static")

# 运行产物目录（可用环境变量覆盖，便于测试）
WORK_DIR = os.environ.get("WX2TG_WORK_DIR") or os.path.join(BASE_DIR, "work")

PREVIEW_DIR = os.path.join(WORK_DIR, "preview")

# 上传临时文件的落盘目录（在 WORK_DIR 下）
UPLOAD_DIR = os.path.join(WORK_DIR, "uploads")


def ensure_dirs() -> None:
    """确保运行所需的目录存在。"""
    for path in (WORK_DIR, STATIC_FOLDER, PREVIEW_DIR, UPLOAD_DIR):
        os.makedirs(path, exist_ok=True)


def get_env_config():
    """每次调用时重新读取 Telegram 环境变量。

    刻意不在模块加载时缓存 Token：BAT 中临时 set 的环境变量
    只对子进程生效，每次读取才能拿到最新值。
    """
    token = os.environ.get("TG_BOT_TOKEN", "").strip()
    owner_id = os.environ.get("TG_OWNER_ID", "").strip()
    bot_name = os.environ.get("TG_BOT_NAME", "").strip().lstrip("@").lower()
    return token, owner_id, bot_name


def print_diagnostics() -> None:
    """启动诊断输出：告诉用户环境配置是否就绪。"""

    token, owner_id, bot_name = get_env_config()

    print()
    print("=" * 60)
    print("微信自定义表情 → Telegram Sticker")
    print("=" * 60)
    print()
    print("访问地址：http://127.0.0.1:5000")
    print()
    print("TG_BOT_TOKEN：" + ("已配置" if token else "未配置（无法上传）"))
    print("TG_OWNER_ID：" + (owner_id if owner_id else "未配置（无法上传）"))
    print("TG_BOT_NAME：" + (bot_name if bot_name else "未配置（上传时自动从 getMe 获取）"))
    print()
    print("运行目录：" + WORK_DIR)
    print()
