# -*- coding: utf-8 -*-
"""统一日志：替代散落各处的 print。

用法：from weixin2tg.logging_setup import get_logger
      logger = get_logger(__name__)
"""

import logging
import sys

_LOGGER_NAME = "weixin2tg"


def setup_logging(level=logging.INFO):
    """配置单例 logger（幂等：重复调用不会叠加 handler）。"""
    logger = logging.getLogger(_LOGGER_NAME)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s %(name)s: %(message)s",
                datefmt="%H:%M:%S",
            )
        )
        logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False
    return logger


def get_logger(name=None):
    """获取带统一格式的 logger。

    name 建议传 __name__，方便定位日志来源模块。
    """
    setup_logging()
    return logging.getLogger(name or _LOGGER_NAME)
