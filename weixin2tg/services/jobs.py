# -*- coding: utf-8 -*-
"""Job 内存模型与后台任务。

- JOBS：进程内任务表 {job_id: job_dict}
- run_build_job：转码 + 打包（状态机 running → done / error）
- run_upload_job：全自动上传到 Telegram
- cleanup_old_jobs：定期清理过期任务与 zip

上传进度换算说明：静态/动图各自调用 uploader.upload_set，
进度回调给出「该类型内百分比」；这里累加成全局百分比，避免动图
阶段进度条从 0 回退。
"""

import os
import shutil
import threading
import time
import uuid

from weixin2tg import config
from weixin2tg.logging_setup import get_logger
from weixin2tg.services import packer
from weixin2tg.services.converter import (
    build_animated_sticker,
    build_static_sticker,
)
from weixin2tg.services.scanner import prepare_items, sniff_format
from weixin2tg.telegram import client
from weixin2tg.telegram.uploader import upload_set

logger = get_logger(__name__)

# 任务保留时长（2 小时）
JOB_MAX_AGE = 2 * 60 * 60
# 清理线程间隔
_CLEANUP_INTERVAL = 600

JOBS = {}

_cleanup_started = False


# ============================================================
# Job 基础
# ============================================================

def gen_id(length=12):
    return uuid.uuid4().hex[:length]


def make_job():
    """新建一个 running 状态的 job。"""
    return {
        "state": "running",
        "percent": 0,
        "message": "",
        "error": None,
        "results": None,
        "output": [],        # 过程日志（行文本）
        "_created_at": time.time(),
        # 构建产物（仅 build job 使用）
        "zip_path": None,
        "files": None,
    }


def job_public(job):
    """返回可安全暴露给前端的字段（不含内部/绝对路径信息）。"""
    return {
        "state": job.get("state"),
        "percent": job.get("percent", 0),
        "message": job.get("message", ""),
        "error": job.get("error"),
        "results": job.get("results"),
        "output": job.get("output", []),
    }


# ============================================================
# 构建 Job（转码 + 打包）
# ============================================================

def start_build_job(selected, pack_name, ffmpeg_path):
    """创建并启动构建任务，返回 job_id。"""
    job_id = gen_id()
    JOBS[job_id] = make_job()

    thread = threading.Thread(
        target=run_build_job,
        args=(job_id, selected, pack_name, ffmpeg_path),
        daemon=True,
    )
    thread.start()
    return job_id


def run_build_job(job_id, selected, pack_name, ffmpeg_path):
    """后台执行：逐文件转码 → 写 README → 打包 zip。"""
    job = JOBS.get(job_id)
    if job is None:
        logger.error("run_build_job: job %s 不存在", job_id)
        return

    failures = []

    def fail(name, error):
        failures.append({"name": name, "error": str(error)})
        logger.warning("转换失败 %s -> %s", name, error)

    try:
        if not selected:
            raise RuntimeError("没有选择任何表情")

        output_dir = os.path.join(config.WORK_DIR, job_id)
        shutil.rmtree(output_dir, ignore_errors=True)
        static_dir = os.path.join(output_dir, "static")
        animated_dir = os.path.join(output_dir, "animated")
        os.makedirs(static_dir, exist_ok=True)
        os.makedirs(animated_dir, exist_ok=True)

        static_files = []
        animated_files = []
        total = len(selected)

        for index, item in enumerate(selected, 1):
            job["percent"] = int((index - 1) / max(total, 1) * 80)
            item_id = item.get("id", gen_id())
            name = item.get("name", item_id)
            source = item.get("path")

            if not source or not os.path.isfile(source):
                fail(name, "源文件不存在")
                continue

            job["message"] = f"正在转换 {index}/{total}: {name}"

            # kind 缺失（历史遗留数据）时按内容重新识别
            kind = item.get("kind")
            if kind not in ("static", "gif"):
                kind = sniff_format(source)
            if kind is None:
                fail(name, "无法识别的图片格式")
                continue

            try:
                if kind == "static":
                    out_base = os.path.join(static_dir, item_id)
                    filename = build_static_sticker(source, out_base)
                    static_files.append(os.path.join(static_dir, filename))

                elif kind == "gif":
                    if not ffmpeg_path:
                        raise RuntimeError("没有找到 FFmpeg，无法转换 GIF/动态 WebP")
                    out_base = os.path.join(animated_dir, item_id)
                    filename = build_animated_sticker(source, out_base, ffmpeg_path)
                    animated_files.append(os.path.join(animated_dir, filename))
            except Exception as exc:  # noqa: BLE001
                fail(name, exc)

        # README + ZIP
        packer.write_readme(output_dir, pack_name or "stickers")
        zip_path = os.path.join(config.WORK_DIR, f"{job_id}.zip")
        packer.make_zip(output_dir, zip_path)

        job["zip_path"] = zip_path
        job["files"] = {
            "static": static_files,
            "animated": animated_files,
        }
        job["percent"] = 100
        job["message"] = f"转换完成：静态 {len(static_files)} 个，动态 {len(animated_files)} 个"
        job["results"] = {
            "static_count": len(static_files),
            "anim_count": len(animated_files),
            "failures": failures,
        }
        job["state"] = "done"

    except Exception as exc:  # noqa: BLE001
        logger.exception("构建任务 %s 失败", job_id)
        job["state"] = "error"
        job["error"] = str(exc)
        job["message"] = str(exc)


# ============================================================
# 扫描 Job（上传文件夹后的识别 + 预览，后台逐文件推进）
# ============================================================

def start_scan_job(raw_items):
    """创建并启动扫描任务（识别格式 + 生成预览），返回 job_id。

    raw_items：已落盘的原始文件列表 [{id, name, path}, ...]。
    done 后 job.results.items 为带 kind/size/preview 的可用文件列表。
    """
    job_id = gen_id()
    JOBS[job_id] = make_job()

    thread = threading.Thread(
        target=run_scan_job,
        args=(job_id, raw_items),
        daemon=True,
    )
    thread.start()
    return job_id


def run_scan_job(job_id, raw_items):
    """后台执行：逐文件识别格式 → 生成预览，实时写回进度。"""
    job = JOBS.get(job_id)
    if job is None:
        logger.error("run_scan_job: job %s 不存在", job_id)
        return

    try:
        total = len(raw_items)
        job["message"] = f"识别 0/{total}"

        def on_step(phase, index, count, name):
            job["percent"] = min(99, int(index / max(count, 1) * 100))
            job["message"] = f"{phase} {index}/{count}: {name}"

        result = prepare_items(raw_items, on_step=on_step)
        job["percent"] = 100
        job["message"] = f"读取完成：共 {len(result)} 个可用文件"
        job["results"] = {"items": result}
        job["state"] = "done"

    except Exception as exc:  # noqa: BLE001
        logger.exception("扫描任务 %s 失败", job_id)
        job["state"] = "error"
        job["error"] = str(exc)
        job["message"] = str(exc)


# ============================================================
# 上传 Job（全自动上传 Telegram）
# ============================================================

def start_upload_job(
    token,
    owner_id,
    static_files,
    anim_files,
    base_static,
    base_anim,
    title_static,
    title_anim,
    static_packs=None,
    anim_packs=None,
):
    """创建并启动上传任务，返回 job_id。"""
    job_id = gen_id()
    JOBS[job_id] = make_job()

    thread = threading.Thread(
        target=run_upload_job,
        args=(
            job_id, token, owner_id,
            static_files, anim_files,
            base_static, base_anim,
            title_static, title_anim,
            static_packs, anim_packs,
        ),
        daemon=True,
    )
    thread.start()
    return job_id


def run_upload_job(
    job_id,
    token,
    owner_id,
    static_files,
    anim_files,
    base_static,
    base_anim,
    title_static,
    title_anim,
    static_packs=None,
    anim_packs=None,
):
    """后台执行：getMe → 静态上传 → 动图上传。"""
    job = JOBS.get(job_id)
    if job is None:
        logger.error("run_upload_job: job %s 不存在", job_id)
        return

    def log(line):
        job["output"].append(line)

    try:
        # ---------- 参数检查 ----------
        if not (token or "").strip():
            raise RuntimeError("TG_BOT_TOKEN 未配置")
        owner_id = str(owner_id or "").strip()
        if not owner_id:
            raise RuntimeError("TG_OWNER_ID 未配置")
        if not owner_id.isdigit():
            raise RuntimeError(f"TG_OWNER_ID 必须是数字：{owner_id}")

        # ---------- 获取 Bot 信息 ----------
        job["message"] = "正在获取 Telegram Bot 信息…"
        me = client.tg_call(token, "getMe")
        bot_uname = (me.get("username") or "").strip().lower()
        if not bot_uname:
            raise RuntimeError("Telegram Bot 没有 username")
        log(f"Telegram Bot：@{bot_uname}")

        # 进度：uploader 内部已按「本次实际计划上传文件」（勾选分包）计算完成度，
        # 这里直接透传——保证 X/total 与实际勾选一致，不再用全量文件做分母。
        # 注：静态/动图两段各自从 0 推进，类型切换瞬间进度条会归零一次，
        # 但每段内的百分比与 total 展示是准确无误的。
        def make_progress():
            def callback(percent, message):
                job["percent"] = min(99, int(percent))
                job["message"] = message
            return callback

        # ---------- 静态贴纸 ----------
        created = []
        if static_files:
            job["message"] = "开始上传静态贴纸…"
            created.extend(
                upload_set(
                    token=token,
                    owner_id=owner_id,
                    base_name=base_static,
                    title=title_static,
                    kind="static",
                    files_list=static_files,
                    bot_uname=bot_uname,
                    chunk_nums=static_packs,
                    label="静态",
                    progress=make_progress(),
                )
            )
            log(f"静态贴纸包完成：{'、'.join(created[-10:])}")

        # ---------- 动态贴纸 ----------
        if anim_files:
            job["message"] = "开始上传动态贴纸…"
            created.extend(
                upload_set(
                    token=token,
                    owner_id=owner_id,
                    base_name=base_anim,
                    title=title_anim,
                    kind="video",
                    files_list=anim_files,
                    bot_uname=bot_uname,
                    chunk_nums=anim_packs,
                    label="动态",
                    progress=make_progress(),
                )
            )
            log(f"动态贴纸包完成：{'、'.join(created[-10:])}")

        # ---------- 完成 ----------
        job["results"] = {"created": created}
        job["percent"] = 100
        job["message"] = f"上传完成，共创建 {len(created)} 个 Sticker Pack"
        job["state"] = "done"

    except Exception as exc:  # noqa: BLE001
        logger.exception("上传任务 %s 失败", job_id)
        job["state"] = "error"
        job["error"] = str(exc)
        job["message"] = str(exc)


# ============================================================
# 清理线程
# ============================================================

def cleanup_old_jobs():
    """定期清理超过 JOB_MAX_AGE 的任务（含 zip 文件）。"""
    while True:
        try:
            now = time.time()
            remove_ids = [
                job_id
                for job_id, job in JOBS.items()
                if now - job.get("_created_at", now) > JOB_MAX_AGE
            ]

            for job_id in remove_ids:
                job = JOBS.pop(job_id, None)
                if not job:
                    continue
                zip_path = job.get("zip_path")
                if zip_path and os.path.isfile(zip_path):
                    try:
                        os.remove(zip_path)
                    except OSError as exc:
                        # 不再静默吞异常：记录日志（不影响主流程）
                        logger.warning("清理 zip 失败 %s: %s", zip_path, exc)
                logger.info("已清理过期任务 %s", job_id)
        except Exception:
            # 清理循环不能因单次异常退出，但必须留下痕迹便于排查
            logger.exception("cleanup_old_jobs 异常")

        time.sleep(_CLEANUP_INTERVAL)


def start_cleanup_thread():
    """启动清理线程（幂等，避免重复起多个循环）。"""
    global _cleanup_started
    if _cleanup_started:
        return
    _cleanup_started = True
    thread = threading.Thread(target=cleanup_old_jobs, daemon=True)
    thread.start()
