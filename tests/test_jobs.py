# -*- coding: utf-8 -*-
"""jobs：Job 状态机与构建任务。"""

import io
import os

from PIL import Image

from weixin2tg.services import jobs as jobs_mod


def _png_bytes(size=(64, 64)):
    buf = io.BytesIO()
    Image.new("RGBA", size, (10, 200, 30, 255)).save(buf, "PNG")
    return buf.getvalue()


def test_make_job_fields():
    job = jobs_mod.make_job()
    assert job["state"] == "running"
    assert job["percent"] == 0
    assert job["error"] is None
    assert job["results"] is None
    assert isinstance(job["output"], list)


def test_job_public_hides_internal_keys():
    job = jobs_mod.make_job()
    job["zip_path"] = "C:/secret/path.zip"
    job["files"] = {"static": ["C:/secret/1.png"]}
    public = jobs_mod.job_public(job)
    assert "zip_path" not in public
    assert "files" not in public
    assert "_created_at" not in public
    assert public["state"] == "running"


def test_build_job_done_state(tmp_path):
    # 准备一个合法的 PNG 源文件
    src = tmp_path / "emo.png"
    src.write_bytes(_png_bytes())

    job_id = jobs_mod.start_build_job(
        selected=[{"id": "f1", "name": "emo.png", "path": str(src), "kind": "static"}],
        pack_name="test_pack",
        ffmpeg_path=None,
    )

    # 等待完成（后台线程）
    job = jobs_mod.JOBS[job_id]
    deadline = 0
    import time

    for _ in range(200):
        if job["state"] in ("done", "error"):
            break
        time.sleep(0.05)
    else:
        raise AssertionError("build job 超时")

    assert job["state"] == "done"
    assert job["results"]["static_count"] == 1
    assert job["results"]["anim_count"] == 0
    assert job["results"]["failures"] == []
    assert job["percent"] == 100

    # 产物落盘 + zip 生成
    assert os.path.isfile(os.path.join(jobs_mod.config.WORK_DIR, job_id, "static", "f1.png"))
    assert os.path.isfile(job["zip_path"])


def test_build_job_no_ffmpeg_fails_gif(tmp_path):
    src = tmp_path / "a.gif"
    src.write_bytes(b"GIF89a" + b"0" * 64)  # 内容识别为 gif，但 ffmpeg 为 None

    job_id = jobs_mod.start_build_job(
        selected=[{"id": "g1", "name": "a.gif", "path": str(src), "kind": "gif"}],
        pack_name="p",
        ffmpeg_path=None,
    )
    job = jobs_mod.JOBS[job_id]
    import time

    for _ in range(200):
        if job["state"] in ("done", "error"):
            break
        time.sleep(0.05)

    # 单个文件失败不算 job 失败，而是计入 failures（job 仍 done）
    assert job["state"] == "done"
    assert job["results"]["anim_count"] == 0
    assert len(job["results"]["failures"]) == 1
    assert "FFmpeg" in job["results"]["failures"][0]["error"]


def test_build_job_missing_file_is_failure(tmp_path):
    job_id = jobs_mod.start_build_job(
        selected=[{"id": "x1", "name": "gone.png", "path": str(tmp_path / "gone.png"), "kind": "static"}],
        pack_name="p",
        ffmpeg_path=None,
    )
    job = jobs_mod.JOBS[job_id]
    import time

    for _ in range(200):
        if job["state"] in ("done", "error"):
            break
        time.sleep(0.05)

    assert job["state"] == "done"
    assert job["results"]["static_count"] == 0
    assert job["results"]["failures"][0]["name"] == "gone.png"
