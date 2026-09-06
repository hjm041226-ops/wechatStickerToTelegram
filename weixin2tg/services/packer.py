# -*- coding: utf-8 -*-
"""打包：生成 README.txt 与 stickers.zip。"""

import os
import zipfile

from weixin2tg.logging_setup import get_logger

logger = get_logger(__name__)


def write_readme(output_dir, pack_name):
    """在输出目录写入 README.txt（手动上传 @Stickers 时的指引）。"""
    readme_path = os.path.join(output_dir, "README.txt")
    with open(readme_path, "w", encoding="utf-8") as f:
        f.write(
            "微信自定义表情 → Telegram Sticker\n"
            "====================================\n\n"
            "静态贴纸：static/\n"
            "动态贴纸：animated/\n\n"
            "Telegram 创建贴纸包：\n"
            "1. 打开 @Stickers\n"
            "2. 静态贴纸使用 /newpack\n"
            "3. 视频贴纸使用 /newvideo\n"
            "4. 按 Telegram 提示上传文件\n\n"
            f"基础贴纸包名称：{pack_name}\n"
        )
    return readme_path


def make_zip(output_dir, zip_path):
    """把输出目录（含 README/static/animated）压缩为 zip。"""
    if os.path.exists(zip_path):
        os.remove(zip_path)

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for root, _dirs, files in os.walk(output_dir):
            for filename in sorted(files):
                full_path = os.path.join(root, filename)
                arcname = os.path.relpath(full_path, output_dir)
                z.write(full_path, arcname)

    return zip_path
