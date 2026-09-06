# -*- coding: utf-8 -*-
"""converter：静态贴纸缩放 + WebP fallback。"""

import io
import os

import pytest
from PIL import Image

from weixin2tg.services.converter import build_static_sticker


def _make_image(size, color=(255, 0, 0, 255), fmt="PNG"):
    buf = io.BytesIO()
    Image.new("RGBA", size, color).save(buf, fmt)
    buf.seek(0)
    return buf


def test_scales_down_to_512(tmp_path):
    src = tmp_path / "big.png"
    src.write_bytes(_make_image((1024, 512)).read())
    out_base = str(tmp_path / "out")
    filename = build_static_sticker(str(src), out_base)

    assert filename == "out.png"
    with Image.open(out_base + ".png") as im:
        assert im.size == (512, 256)


def test_small_image_scaled_up_to_512(tmp_path):
    # Telegram 贴纸要求长边 512，小图也会被放大到 512 边
    src = tmp_path / "small.png"
    src.write_bytes(_make_image((100, 80)).read())
    out_base = str(tmp_path / "out")
    filename = build_static_sticker(str(src), out_base)

    assert filename == "out.png"
    with Image.open(out_base + ".png") as im:
        assert im.size == (512, 410)  # round(100*5.12)=512, round(80*5.12)=410


def test_large_png_falls_back_to_webp(tmp_path):
    # 纯色 2000x2000 随机噪点 PNG，压缩后必然 >512KB → 应产出 .webp
    rng = __import__("random").Random(42)
    noisy = Image.new("RGBA", (2000, 2000))
    noisy.putdata([(rng.randrange(256), rng.randrange(256), rng.randrange(256), 255) for _ in range(2000 * 2000)])
    src = tmp_path / "noise.png"
    noisy.save(str(src), "PNG")

    assert os.path.getsize(str(src)) > 512 * 1024

    out_base = str(tmp_path / "out")
    filename = build_static_sticker(str(src), out_base)

    assert filename == "out.webp", "超过 512KB 时应回退为 WebP"
    assert os.path.isfile(out_base + ".webp")
    assert not os.path.isfile(out_base + ".png"), "PNG 应被删除"


def test_invalid_image_raises(tmp_path):
    src = tmp_path / "bad.png"
    src.write_bytes(b"not an image at all.......")
    with pytest.raises(Exception):
        build_static_sticker(str(src), str(tmp_path / "out"))
