# -*- coding: utf-8 -*-
"""上传路由：/api/upload（含 history_id 复用）、/api/preset。

字段契约（与前端 static/app.js 对齐）：
- POST /api/upload
    body（二选一来源）：
        job_id: 本次生成的任务 id（复用刚 build 的产物）
        history_id: 历史包 id（复用历史 work/<id> 产物）
    其余：title / static_name / anim_name / static_packs[] / anim_packs[]
- GET /api/preset  返回 {ok, has_token, owner_id, bot_name}
"""

from flask import Blueprint, jsonify, request

from weixin2tg import config
from weixin2tg.logging_setup import get_logger
from weixin2tg.services.history import get_artifacts
from weixin2tg.services.jobs import start_upload_job

logger = get_logger(__name__)

bp = Blueprint("upload", __name__, url_prefix="/api")


@bp.post("/upload")
def api_upload():
    """全自动上传：job_id（本次生成）或 history_id（历史包）二选一。

    两种来源最终都从磁盘 work/<id>/static|animated 读取文件，
    因此不依赖内存任务是否仍在 JOBS 中。
    """
    try:
        data = request.get_json(silent=True) or {}

        # ---------------- 来源定位：job_id / history_id ----------------
        source_id = data.get("history_id") or data.get("job_id")
        if not source_id:
            return jsonify({"ok": False, "error": "缺少 job_id 或 history_id"}), 400

        artifacts = get_artifacts(config.WORK_DIR, source_id)
        if not artifacts["exists"]:
            return jsonify({
                "ok": False,
                "error": f"找不到该任务/历史包的产物：{source_id}（可能已被清理）",
            }), 404

        static_files = artifacts["static"]
        anim_files = artifacts["animated"]
        if not static_files and not anim_files:
            return jsonify({"ok": False, "error": "该历史包没有任何可上传的贴纸文件"}), 400

        # ---------------- Telegram 凭证（环境变量优先） ----------------
        env_token, env_owner_id, _ = config.get_env_config()
        token = str(data.get("bot_token") or env_token or "").strip()
        owner_id = str(data.get("owner_id") or env_owner_id or "").strip()

        if not token:
            return jsonify({"ok": False, "error": "TG_BOT_TOKEN 未配置（请在 start.bat 中设置）"}), 400
        if not owner_id:
            return jsonify({"ok": False, "error": "TG_OWNER_ID 未配置（请在 start.bat 中设置）"}), 400

        # ---------------- 名称 / 标题映射（前端字段 static_name/anim_name/title） ----------------
        title = str(data.get("title") or "").strip() or "WeChat Stickers"
        base_static = str(data.get("static_name") or "").strip() or "stickers"
        base_anim = (
            str(data.get("anim_name") or "").strip()
            or f"{base_static}_video"
        )
        # 兼容旧前端字段 title_static / title_anim
        title_static = str(data.get("title_static") or title).strip() or title
        title_anim = str(data.get("title_anim") or title).strip() or title

        def parse_packs(value):
            """static_packs/anim_packs：数组 → 排序去重后的 int 列表；None → 全传。"""
            if value is None:
                return None
            if not isinstance(value, (list, tuple)):
                value = [value]
            return sorted({int(x) for x in value if str(x).isdigit()})

        static_packs = parse_packs(data.get("static_packs"))
        anim_packs = parse_packs(data.get("anim_packs"))
        # 说明：[] 表示用户没勾选该类型的任何包 → uploader 直接跳过；
        # None 才表示「全部上传」（前端总是传数组，历史接口保留 None 兼容）。

        job_id = start_upload_job(
            token=token,
            owner_id=owner_id,
            static_files=static_files,
            anim_files=anim_files,
            base_static=base_static,
            base_anim=base_anim,
            title_static=title_static,
            title_anim=title_anim,
            static_packs=static_packs,
            anim_packs=anim_packs,
        )
        logger.info("upload job %s 启动：来源=%s 静态=%d 动图=%d",
                    job_id, "history_id" if data.get("history_id") else "job_id",
                    len(static_files), len(anim_files))
        return jsonify({"ok": True, "job_id": job_id})

    except Exception as exc:  # noqa: BLE001
        logger.exception("/api/upload 失败")
        return jsonify({"ok": False, "error": str(exc)}), 500


@bp.route("/preset", methods=["GET", "POST"])
def api_preset():
    """GET：返回环境变量配置状态（不返回完整 Token）。"""
    if request.method == "GET":
        token, owner_id, bot_name = config.get_env_config()
        return jsonify({
            "ok": True,
            "has_token": bool(token),
            "owner_id": owner_id,
            "bot_name": bot_name,
        })

    # POST 保留兼容（前端不使用）
    data = request.get_json(silent=True) or {}
    return jsonify({"ok": True, "data": data})
