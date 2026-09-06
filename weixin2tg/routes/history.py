# -*- coding: utf-8 -*-
"""历史包路由：/api/history。"""

from flask import Blueprint, jsonify

from weixin2tg import config
from weixin2tg.services.history import scan_history
from weixin2tg.services.jobs import JOBS

bp = Blueprint("history", __name__, url_prefix="/api")


@bp.get("/history")
def api_history():
    """列出历史生成的贴纸包（磁盘产物）。

    返回 {ok, items: [{id, time, static, anim}]}，
    其中 static/anim 是该历史包静态/动图的文件数量。
    正在运行的任务会被跳过。
    """
    running_ids = [jid for jid, job in JOBS.items() if job.get("state") == "running"]
    items = scan_history(config.WORK_DIR, running_ids=running_ids)
    return jsonify({"ok": True, "items": items})
