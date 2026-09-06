# -*- coding: utf-8 -*-
"""Telegram Bot API 统一客户端。

所有对 Telegram 的 HTTP 调用都收敛到这里，统一处理：
- 超时与重试（网络抖动 / 429 / 5xx 自动退避）
- 429 自动读取 parameters.retry_after
- 错误归一为 TgError，供上层翻译成用户友好消息

模块以「client.xxx」的方式被引用（见 sticker.py / uploader.py），
这样测试时 monkeypatch 单个函数即可完整模拟 Telegram。
"""

import threading
import time

import requests
from requests.exceptions import SSLError as RequestsSSLError

from weixin2tg.logging_setup import get_logger

logger = get_logger(__name__)

# Bot API 地址模板
TG_API = "https://api.telegram.org/bot{token}/{method}"

# 可重试的状态码（429 限流 / 5xx 服务端错误）
RETRYABLE_HTTP = (429, 500, 502, 503, 504)

# 网络层可重试异常（SSLError 是其子类 ConnectionError 派生，一并覆盖）
_NETWORK_ERRORS = (
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
    requests.exceptions.ChunkedEncodingError,
)

# 模块级 Session 单例：所有 tg_call 复用同一组连接，
# 避免每次都新建 TCP+TLS 连接（直连 api.telegram.org 时单次握手 ~100-300ms，
# 120 张贴纸累计省 10-30s）。
# 连接池大小设到 20，远超默认并发上限 _UPLOAD_WORKERS=3，留足余量。
_SESSION = requests.Session()
_ADAPTER = requests.adapters.HTTPAdapter(
    pool_connections=20,
    pool_maxsize=20,
)
_SESSION.mount("https://", _ADAPTER)
_SESSION.mount("http://", _ADAPTER)


class TgError(RuntimeError):
    """归一化的 Telegram API 错误。

    属性：
    - error_code：Telegram error_code（或 HTTP 状态码）
    - description：Telegram 返回的描述文本
    - retry_after：429 时 Telegram 建议等待的秒数（可能为 None）
    """

    def __init__(self, message, *, error_code=None, description="", parameters=None):
        super().__init__(message)
        self.error_code = error_code
        self.description = description or ""
        self.parameters = parameters or {}
        self.retry_after = self.parameters.get("retry_after")


def _rewind_files(files):
    """multipart 重试前把文件指针拨回开头，避免重复读空文件。"""
    if not files:
        return
    for fobj in files.values():
        seek = getattr(fobj, "seek", None)
        if seek:
            try:
                seek(0)
            except Exception:
                pass


# 全局请求节流闸：仅对显式传入 min_interval 的调用生效。
# 背景：Telegram 对 addStickerToSet / createNewStickerSet 有分钟级写入配额，
# 并发 worker 若同时发请求会集体撞 429 并各自罚站 retry_after（可达 50s+）；
# 主动把请求错峰匀速化，远比自己吃 50s 惩罚划算。
_gate_lock = threading.Lock()
_gate_last = 0.0  # 上一次被闸放行的实际时刻（monotonic）


def _gate_wait(min_interval):
    """若 min_interval > 0，保证任意两次实际发送间隔 >= min_interval 秒。

    放在每次发送（含 429/网络错误后的重试发送）之前，这样即使多个 worker
    同时被 429 罚站到同一时刻醒来，重试也会再被错峰，避免齐醒齐发再次撞限流。
    """
    if min_interval <= 0:
        return
    global _gate_last
    with _gate_lock:
        now = time.monotonic()
        wait = _gate_last + min_interval - now
        if wait > 0:
            time.sleep(wait)
            now = time.monotonic()
        _gate_last = now


def tg_call(token, method, data=None, files=None, *, timeout=60, retries=4, base_delay=1.0, min_interval=0.0):
    """调用 Telegram Bot API（带重试）。

    成功时返回响应 JSON 的 result 字段。
    失败时抛出 TgError；429 / 5xx / 网络异常自动退避重试，
    重试耗尽或 4xx 业务错误直接抛出。

    注意：files 的值为文件对象时，重试期间会自动 seek(0)，
    调用方无需自行维护文件指针。

    重试参数说明（针对直连 api.telegram.org 易出现瞬时 TLS 断连的情况）：
    - 默认 4 次重试（共 5 次尝试），退避从 1s 起按 1.5× 增长、上限 10s
    - SSL 类错误（SSLEOFError 等）说明 TLS 握手/传输中途被掐断，
      往往是瞬时干扰或并发过高触发，按 1.5× 间隔退避再试
    - 429 时尊重 Telegram 的 retry_after（最高 60s），后续重试上限 10s

    min_interval：可选的最小请求间隔（秒），>0 时在每次实际发送前
    过全局节流闸，用于 addStickerToSet 这类有写入配额、多并发容易
    集体撞 429 的接口（由 uploader 显式传入，普通查询不受影响）。
    """
    token = (token or "").strip()
    if not token:
        raise TgError(f"{method}: TG_BOT_TOKEN 未配置")

    url = TG_API.format(token=token, method=method)
    delay = float(base_delay)
    last_network_error = None

    for attempt in range(1, retries + 2):
        _rewind_files(files)
        _gate_wait(min_interval)

        try:
            response = _SESSION.post(url, data=data or {}, files=files, timeout=timeout)
        except _NETWORK_ERRORS as exc:
            # 网络层失败：退避重试（SSL 断连按 1.5× 间隔；常规错误也走同一上限）
            last_network_error = exc
            logger.warning(
                "%s 网络错误(%s)，第 %s/%s 次重试",
                method, exc.__class__.__name__, attempt, retries,
            )
            if attempt > retries:
                break
            wait = delay * 1.5 if isinstance(exc, RequestsSSLError) else delay
            time.sleep(min(wait, 10))
            delay = min(delay * 1.5, 10)
            continue

        try:
            payload = response.json()
        except ValueError:
            raise TgError(
                f"{method}: Telegram 返回非 JSON：{response.text[:500]}",
                error_code=response.status_code,
            )

        if payload.get("ok"):
            return payload.get("result")

        code = payload.get("error_code") or response.status_code
        description = payload.get("description") or ""
        params = payload.get("parameters") or {}

        if code in RETRYABLE_HTTP:
            # 429 / 5xx：按 retry_after（若有）或退避间隔重试
            if attempt > retries:
                raise TgError(
                    f"{method}: 多次重试仍失败：{description or code}",
                    error_code=code, description=description, parameters=params,
                )
            wait = float(params.get("retry_after") or delay)
            logger.info("%s 限流/服务端错误(%s)，%.1fs 后重试", method, code, wait)
            time.sleep(min(wait, 60))
            delay = min(max(delay * 2, wait), 10)
            continue

        # 其它 4xx：业务错误，直接抛出
        raise TgError(
            f"{method}: {description or code}",
            error_code=code, description=description, parameters=params,
        )

    raise TgError(f"{method}: 网络请求失败：{last_network_error}")
