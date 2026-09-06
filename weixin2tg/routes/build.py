# -*- coding: utf-8 -*-
"""构建相关路由：/api/build、/api/status/<id>、/api/download/<id>、/api/ffmpeg-check。

实际路由名以现状为准（前端 app.js 用 /api/status 轮询、/api/download 下载），
与 README 表格一致。
"""

import os

from flask import Blueprint, jsonify, request, send_file

from weixin2tg import config
from weixin2tg.logging_setup import get_logger
from weixin2tg.services.converter import find_ffmpeg
from weixin2tg.services.jobs import JOBS, job_public, start_build_job

logger = get_logger(__name__)

bp = Blueprint("build", __name__, url_prefix="/api")


@bp.post("/build")
def api_build():
    """启动贴纸包生成（后台线程），立即返回 job_id。"""
    try:
        data = request.get_json(silent=True) or {}
        selected = data.get("items") or []
        if not isinstance(selected, list) or not selected:
            return jsonify({"ok": False, "error": "请先勾选至少一个表情"}), 400

        pack_name = str(data.get("pack_name") or "").strip() or "stickers"
        ffmpeg_path = find_ffmpeg(data.get("ffmpeg_path") or None)

        # 只保留合法的 item（含有效路径），其余忽略
        valid = [
            it for it in selected
            if isinstance(it, dict) and it.get("path") and os.path.isfile(it.get("path"))
        ]
        if not valid:
            return jsonify({"ok": False, "error": "所选文件不存在，请重新扫描"}), 400

        job_id = start_build_job(valid, pack_name, ffmpeg_path)
        return jsonify({"ok": True, "job_id": job_id})

    except Exception as exc:  # noqa: BLE001
        logger.exception("/api/build 失败")
        return jsonify({"ok": False, "error": str(exc)}), 500


@bp.get("/status/<job_id>")
def api_status(job_id):
    """轮询任务进度。"""
    job = JOBS.get(job_id)
    if not job:
        return jsonify({"ok": False, "error": "Job 不存在"}), 404
    return jsonify({"ok": True, **job_public(job)})


@bp.get("/download/<job_id>")
def api_download(job_id):
    """下载生成好的 stickers.zip（直接按磁盘约定定位，不依赖内存任务）。"""
    zip_path = os.path.join(config.WORK_DIR, f"{job_id}.zip")
    if not os.path.isfile(zip_path):
        return jsonify({"ok": False, "error": "ZIP 文件不存在（可能已过期清理）"}), 404
    return send_file(
        zip_path,
        as_attachment=True,
        download_name="telegram_stickers.zip",
    )


@bp.get("/ffmpeg-check")
def api_ffmpeg_check():
    """前端/调试用：检查 ffmpeg 是否可用。"""
    path = find_ffmpeg()
    return jsonify({"ok": bool(path), "path": path})
