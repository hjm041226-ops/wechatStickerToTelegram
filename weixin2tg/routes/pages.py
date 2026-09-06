# -*- coding: utf-8 -*-
"""页面路由：首页与预览图。"""

import os

from flask import Blueprint, render_template, send_from_directory

from weixin2tg import config

bp = Blueprint("pages", __name__)


@bp.route("/")
def index():
    return render_template("index.html")


@bp.route("/preview/<path:name>")
def preview(name):
    """扫描阶段的网格预览图（存于 PREVIEW_DIR）。"""
    return send_from_directory(config.PREVIEW_DIR, name)
