# -*- coding: utf-8 -*-
"""端到端测试：scan_upload → build → 轮询 → 下载 zip → history → upload（mock Telegram）。

覆盖的契约（与 static/app.js 对齐）：
- /api/scan_upload 落盘后返回 {job_id}，识别/预览在后台扫描任务执行
- /api/build 接收 {items, pack_name}
- /api/status/<id> 轮询，done 后 results 含 static_count/anim_count/failures
- /api/download/<id> 返回 zip
- /api/history 返回 {items: [{id,time,static,anim}]}
- /api/upload 支持 history_id（补全的缺失功能）与 job_id
"""

import io
import zipfile

from PIL import Image


def _png_bytes(size=(96, 96), color=(255, 60, 60, 255)):
    buf = io.BytesIO()
    Image.new("RGBA", size, color).save(buf, "PNG")
    return buf.getvalue()


def _upload_folder(client, filenames, job_waiter):
    """以 multipart 形式模拟「选择文件夹…」上传。

    契约（2026-09-06 起）：/api/scan_upload 落盘后立即返回 {job_id}，
    识别+预览在后台扫描任务执行，需轮询 /api/status/<job_id> 到 done
    后从 results.items 取最终文件列表。
    Werkzeug test client 不支持同名字段列表，故逐文件上传后合并 items
    （后端产物按 work/uploads/<id>/ 隔离，互不影响）。
    """
    all_items = []
    for i, name in enumerate(filenames):
        data = {"files": (io.BytesIO(_png_bytes(color=(50 * i, 120, 200, 255))), name)}
        resp = client.post("/api/scan_upload", data=data, content_type="multipart/form-data")
        assert resp.status_code == 200, resp.get_json()
        job_id = resp.get_json()["job_id"]
        s = job_waiter(client, job_id)
        assert s["state"] == "done", s
        all_items.extend(s["results"]["items"])
    return {"ok": True, "items": all_items, "count": len(all_items)}


def test_preset_has_token(client):
    resp = client.get("/api/preset")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["has_token"] is True
    assert data["owner_id"] == "7654321"


def test_full_flow_history_upload(client, fake_telegram, job_waiter):
    # ---------- ① 上传文件并扫描 ----------
    d = _upload_folder(client, ["red.png", "blue.png"], job_waiter)
    assert d["ok"] is True
    items = d["items"]
    assert len(items) == 2
    for it in items:
        assert it["kind"] == "static"
        assert it["preview"].startswith("/preview/")

    # ---------- ② 启动构建 ----------
    resp = client.post("/api/build", json={"items": items, "pack_name": "e2e_pack"})
    assert resp.status_code == 200, resp.get_json()
    build_job_id = resp.get_json()["job_id"]

    # ---------- ③ 轮询到 done，校验 results 字段 ----------
    s = job_waiter(client, build_job_id)
    assert s["state"] == "done", s
    res = s["results"]
    assert res["static_count"] == 2
    assert res["anim_count"] == 0
    assert res["failures"] == []

    # ---------- ④ 下载 zip ----------
    dl = client.get(f"/api/download/{build_job_id}")
    assert dl.status_code == 200
    with zipfile.ZipFile(io.BytesIO(dl.data)) as z:
        names = z.namelist()
        assert any(n.startswith("static/") and n.endswith(".png") for n in names)
        assert "README.txt" in names

    # ---------- ⑤ 历史列表出现该 job ----------
    hist = client.get("/api/history").get_json()
    entry = next((h for h in hist["items"] if h["id"] == build_job_id), None)
    assert entry is not None, "构建产物应出现在历史列表"
    assert entry["static"] == 2
    assert entry["anim"] == 0
    assert entry["time"]

    # ---------- ⑥ 用 history_id 上传（补全的功能） ----------
    up = client.post("/api/upload", json={
        "history_id": build_job_id,
        "title": "E2E Pack",
        "static_name": "e2e_static",
        "anim_name": "",
        "static_packs": [1],
        "anim_packs": [],
    })
    assert up.status_code == 200, up.get_json()
    up_job_id = up.get_json()["job_id"]

    us = job_waiter(client, up_job_id)
    assert us["state"] == "done", us
    assert us["results"]["created"] == ["e2e_static_by_test_bot"]


def test_upload_with_job_id(client, fake_telegram, job_waiter):
    """job_id 来源同样可上传（走与 history_id 相同的磁盘读取路径）。"""
    d = _upload_folder(client, ["one.png"], job_waiter)
    items = d["items"]

    resp = client.post("/api/build", json={"items": items, "pack_name": "p"})
    build_job_id = resp.get_json()["job_id"]
    s = job_waiter(client, build_job_id)
    assert s["state"] == "done"

    up = client.post("/api/upload", json={
        "job_id": build_job_id,
        "title": "Job Pack",
        "static_name": "jb_pack",
        "anim_name": "",
    })
    assert up.status_code == 200, up.get_json()
    us = job_waiter(client, up.get_json()["job_id"])
    assert us["state"] == "done", us
    assert us["results"]["created"] == ["jb_pack_by_test_bot"]


def test_upload_missing_source_rejected(client, fake_telegram):
    resp = client.post("/api/upload", json={"history_id": "no_such_job", "title": "x"})
    assert resp.status_code == 404


def test_upload_no_token_rejected(client, fake_telegram, monkeypatch, job_waiter):
    monkeypatch.setenv("TG_BOT_TOKEN", "")
    d = _upload_folder(client, ["one.png"], job_waiter)
    resp = client.post("/api/build", json={"items": d["items"]})
    build_job_id = resp.get_json()["job_id"]
    job_waiter(client, build_job_id)

    up = client.post("/api/upload", json={"job_id": build_job_id, "static_name": "x"})
    assert up.status_code == 400
    assert "TG_BOT_TOKEN" in up.get_json()["error"]


def test_scan_folder_missing(client):
    resp = client.post("/api/scan", json={"folder": "Z:/definitely/not/exist"})
    assert resp.status_code in (400, 500)
    assert resp.get_json()["ok"] is False


def test_build_rejects_empty(client):
    resp = client.post("/api/build", json={"items": [], "pack_name": "x"})
    assert resp.status_code == 400


def test_status_unknown_job(client):
    resp = client.get("/api/status/does_not_exist")
    assert resp.status_code == 404
