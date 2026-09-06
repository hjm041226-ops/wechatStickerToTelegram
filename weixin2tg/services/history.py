# -*- coding: utf-8 -*-
"""历史包索引：扫描 work/ 目录，复用之前的构建产物。

产物布局约定（run_build_job 写入）：
    work/<job_id>/README.txt
    work/<job_id>/static/   *.png *.webp
    work/<job_id>/animated/ *.webm

每次 /api/history 扫一次磁盘，结果缓存 30 秒。
"""

import os
import time

from weixin2tg.logging_setup import get_logger

logger = get_logger(__name__)

# 历史包扫描结果缓存（30s）
_CACHE = {"ts": 0.0, "data": None}
_CACHE_TTL = 30

# 贴纸输出扩展名白名单
_STATIC_EXTS = {".png", ".webp"}
_ANIM_EXTS = {".webm"}

# WORK_DIR 下这些子目录不是 job 产物，扫描时跳过
_SKIP_DIRS = {"preview", "uploads"}


def _list_output_files(job_dir, sub_name, exts):
    """列出 job 输出子目录（static/animated）中的贴纸文件，按文件名排序。"""
    files = []
    sub = os.path.join(job_dir, sub_name)
    if not os.path.isdir(sub):
        return files
    for name in sorted(os.listdir(sub)):
        if os.path.splitext(name)[1].lower() in exts:
            files.append(os.path.join(sub, name))
    return files


def get_artifacts(work_dir, job_id):
    """读取某个 job 的磁盘产物。

    返回 {"static": [...], "animated": [...], "exists": bool}；
    目录不存在时 exists=False。
    """
    job_dir = os.path.join(work_dir, str(job_id))
    if not os.path.isdir(job_dir):
        return {"static": [], "animated": [], "exists": False}

    static_files = _list_output_files(job_dir, "static", _STATIC_EXTS)
    anim_files = _list_output_files(job_dir, "animated", _ANIM_EXTS)
    return {
        "static": static_files,
        "animated": anim_files,
        "exists": True,
    }


def scan_history(work_dir, running_ids=(), force=False):
    """扫描 work/ 目录，生成历史包索引（按目录 mtime 倒序）。

    每条记录：
        {id, time, static, anim}
    其中 static/anim 是对应类型文件数量。
    running_ids：正在运行的任务 id（跳过，避免上传半成品）。
    """
    now = time.time()
    if (
        not force
        and _CACHE["data"] is not None
        and now - _CACHE["ts"] < _CACHE_TTL
    ):
        return _CACHE["data"]

    running = set(running_ids or ())
    entries = []

    try:
        names = os.listdir(work_dir)
    except OSError:
        names = []

    for name in names:
        if name in _SKIP_DIRS or name in running:
            continue
        job_dir = os.path.join(work_dir, name)
        if not os.path.isdir(job_dir):
            continue

        static_files = _list_output_files(job_dir, "static", _STATIC_EXTS)
        anim_files = _list_output_files(job_dir, "animated", _ANIM_EXTS)
        if not static_files and not anim_files:
            continue

        # 目录 mtime 视为任务完成时间
        try:
            mtime = os.path.getmtime(job_dir)
        except OSError:
            mtime = now
        time_text = time.strftime("%Y-%m-%d %H:%M", time.localtime(mtime))

        entries.append(
            {
                "id": name,
                "time": time_text,
                "static": len(static_files),
                "anim": len(anim_files),
            }
        )

    entries.sort(key=lambda e: e["time"], reverse=True)

    _CACHE["ts"] = now
    _CACHE["data"] = entries
    return entries


def clear_cache():
    """清空历史索引缓存（测试用）。"""
    _CACHE["ts"] = 0.0
    _CACHE["data"] = None
