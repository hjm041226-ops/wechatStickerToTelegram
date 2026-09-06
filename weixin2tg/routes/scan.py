# -*- coding: utf-8 -*-
"""扫描路由：/api/scan（磁盘路径）、/api/scan_upload（文件上传）。

字段契约（与前端 static/app.js 对齐）：
- POST /api/scan          body {folder: 文件夹路径}
                          返回 {ok, items: [...], count}
- POST /api/scan_upload   multipart files[]
                          快速落盘后返回 {ok, job_id, count}；
                          识别/预览在后台任务执行，前端轮询
                          /api/status/<job_id>（done 后 items 在 results.items）
item 结构：{id, name, path, kind, size, preview}
"""

import os
import re

from flask import Blueprint, jsonify, request

from weixin2tg import config
from weixin2tg.logging_setup import get_logger
from weixin2tg.services.scanner import (
    ALLOWED_EXTS,
    prepare_items,
    scan_folder,
)
from weixin2tg.services.jobs import gen_id, start_scan_job

logger = get_logger(__name__)

bp = Blueprint("scan", __name__, url_prefix="/api")


@bp.post("/scan")
def api_scan():
    """按磁盘路径扫描文件夹（前端「按路径扫描」按钮）。"""
    try:
        data = request.get_json(silent=True) or {}
        folder = str(data.get("folder") or "").strip().strip('"').strip("'")
        if not folder:
            return jsonify({"ok": False, "error": "缺少 folder 参数"}), 400

        items = scan_folder(folder)
        result = prepare_items(items)
        logger.info("scan_folder: %s -> %d 个可用文件", folder, len(result))
        return jsonify({"ok": True, "items": result, "count": len(result)})

    except Exception as exc:  # noqa: BLE001
        logger.exception("/api/scan 失败")
        return jsonify({"ok": False, "error": str(exc)}), 500


@bp.post("/scan_upload")
def api_scan_upload():
    """接收前端「选择文件夹…」上传的文件。

    只做「把 multipart 流落盘到 work/uploads/<random>/」（必须在请求内完成，
    保证文件流可读），识别格式 + 生成预览交给后台扫描任务，
    立即返回 job_id —— 避免几百个文件同步识别时进度条卡在 100% 干等。
    """
    try:
        uploaded = request.files.getlist("files")
        if not uploaded:
            return jsonify({"ok": False, "error": "没有收到任何文件"}), 400

        # 落盘到 work/uploads/<random>/，便于后续 build 读取绝对路径
        temp_dir = os.path.join(config.UPLOAD_DIR, gen_id())
        os.makedirs(temp_dir, exist_ok=True)

        raw_items = []
        for uploaded_file in uploaded:
            if not uploaded_file or not uploaded_file.filename:
                continue
            filename = uploaded_file.filename or "unknown"
            ext = os.path.splitext(filename)[1].lower()
            if ext not in ALLOWED_EXTS:
                continue

            file_id = gen_id()
            safe_name = re.sub(r"[^a-zA-Z0-9_.-]", "_", filename)
            path = os.path.join(temp_dir, f"{file_id}_{safe_name}")
            uploaded_file.save(path)

            raw_items.append({"id": file_id, "name": filename, "path": path})

        if not raw_items:
            return jsonify({"ok": False, "error": "没有可用的图片文件"}), 400

        job_id = start_scan_job(raw_items)
        logger.info("scan_upload: 落盘 %d 个文件，扫描任务 %s 已启动",
                    len(raw_items), job_id)
        return jsonify({"ok": True, "job_id": job_id, "count": len(raw_items)})

    except Exception as exc:  # noqa: BLE001
        logger.exception("/api/scan_upload 失败")
        return jsonify({"ok": False, "error": str(exc)}), 500
