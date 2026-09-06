# -*- coding: utf-8 -*-
"""蓝图注册。"""

from weixin2tg.routes import build, history, pages, scan, upload


def register_blueprints(app):
    """把全部蓝图挂到 app 上。"""
    app.register_blueprint(pages.bp)
    app.register_blueprint(scan.bp)
    app.register_blueprint(build.bp)
    app.register_blueprint(history.bp)
    app.register_blueprint(upload.bp)
