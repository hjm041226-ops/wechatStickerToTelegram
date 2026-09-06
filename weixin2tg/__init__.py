# -*- coding: utf-8 -*-
"""微信表情 → Telegram 贴纸包：应用包。

对外暴露 create_app()，路由注册与目录准备都从这里完成，
app.py 只保留启动入口。
"""

import os

from flask import Flask

from weixin2tg import config
from weixin2tg.routes import register_blueprints


def create_app() -> Flask:
    """Flask app factory：创建应用、准备目录、注册蓝图。"""

    config.ensure_dirs()

    app = Flask(
        __name__,
        static_folder=config.STATIC_FOLDER,
        static_url_path="/static",
        template_folder=os.path.join(config.BASE_DIR, "templates"),
    )

    # 静态资源不缓存，便于前端迭代
    app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0
    app.json.ensure_ascii = False

    register_blueprints(app)

    return app
