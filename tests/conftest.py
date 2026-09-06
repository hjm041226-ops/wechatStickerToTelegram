# -*- coding: utf-8 -*-
"""pytest 公共夹具。

关键点：
- 在导入 weixin2tg 之前设置 WX2TG_WORK_DIR 指向独立临时目录，
  使测试产物（preview/work/jobs）与真实 work/ 完全隔离；
- Telegram 网络层通过 client.tg_call 单点 mock，测试永不真正请求 Telegram。
"""

import os
import shutil
import tempfile

import pytest

# ---- 必须在 import weixin2tg 前设置好环境 ----
_TMP_WORK = tempfile.mkdtemp(prefix="wx2tg_test_work_")
os.environ["WX2TG_WORK_DIR"] = _TMP_WORK
os.environ["TG_BOT_TOKEN"] = "123456:TEST_FAKE_TOKEN"
os.environ["TG_OWNER_ID"] = "7654321"
os.environ["TG_BOT_NAME"] = ""  # 显式置空，验证运行时自动从 getMe 获取


def pytest_sessionfinish(session, exitstatus):
    """测试结束清理临时目录。"""
    shutil.rmtree(_TMP_WORK, ignore_errors=True)


# ---- 被测应用 ----
from weixin2tg import create_app  # noqa: E402
from weixin2tg.telegram import client as tg_client  # noqa: E402


@pytest.fixture()
def app():
    """构建 Flask app（函数级，隔离 job 状态）。"""
    from weixin2tg.services import jobs as jobs_mod

    jobs_mod.JOBS.clear()
    from weixin2tg.services.history import clear_cache

    clear_cache()
    return create_app()


@pytest.fixture()
def client(app):
    """Flask test_client。"""
    return app.test_client()


def make_fake_tg_call():
    """构造一个假的 tg_call：getStickerSet 永远 not found，其余成功。"""
    def fake_tg_call(token, method, data=None, files=None, **kwargs):
        if method == "getMe":
            return {"username": "test_bot", "first_name": "TestBot", "id": 111}
        if method == "getStickerSet":
            raise tg_client.TgError(
                "Bad Request: sticker set not found",
                error_code=400,
                description="Bad Request: sticker set not found",
            )
        # createNewStickerSet / addStickerToSet 等：读取 multipart 后返回成功
        if files:
            for fobj in files.values():
                try:
                    fobj.read()
                except Exception:
                    pass
        return True

    return fake_tg_call


@pytest.fixture()
def fake_telegram(monkeypatch):
    """默认注入：所有 Telegram 调用成功，名称检查总是「可用」。"""
    monkeypatch.setattr(tg_client, "tg_call", make_fake_tg_call())
    return make_fake_tg_call()


def wait_job(client, job_id, timeout=10.0, interval=0.05):
    """轮询任务直到 done/error，返回状态 JSON。"""
    import time

    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = client.get(f"/api/status/{job_id}")
        assert resp.status_code == 200
        data = resp.get_json()
        if data.get("state") in ("done", "error"):
            return data
        time.sleep(interval)
    raise AssertionError(f"任务 {job_id} 超时未结束")


@pytest.fixture()
def job_waiter():
    """把 wait_job 作为 fixture 注入测试模块。"""
    return wait_job
