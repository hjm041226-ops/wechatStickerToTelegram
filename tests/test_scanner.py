# -*- coding: utf-8 -*-
"""scanner：按文件头识别 PNG/JPG/GIF/WEBP/BMP。"""

import os

from weixin2tg.services.scanner import sniff_format


def _write(tmp_path, name, head: bytes):
    path = tmp_path / name
    path.write_bytes(head)
    return str(path)


def test_png(tmp_path):
    assert sniff_format(_write(tmp_path, "a.png", b"\x89PNG\r\n\x1a\n" + b"0" * 16)) == "static"


def test_jpg(tmp_path):
    assert sniff_format(_write(tmp_path, "a.jpg", b"\xff\xd8\xff\xe0" + b"0" * 16)) == "static"


def test_bmp(tmp_path):
    assert sniff_format(_write(tmp_path, "a.bmp", b"BM" + b"0" * 16)) == "static"


def test_gif(tmp_path):
    assert sniff_format(_write(tmp_path, "a.gif", b"GIF89a" + b"0" * 16)) == "gif"
    assert sniff_format(_write(tmp_path, "a87.gif", b"GIF87a" + b"0" * 16)) == "gif"


def test_unknown_returns_none(tmp_path):
    # 文本/未知内容 → None
    assert sniff_format(_write(tmp_path, "x.txt", b"hello world........")) is None


def test_missing_file_returns_none(tmp_path):
    assert sniff_format(str(tmp_path / "nope.png")) is None
