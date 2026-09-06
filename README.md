# 微信表情 → Telegram 贴纸包 导出工具

把微信自定义表情（文件夹里的 png / jpg / gif / webp / bmp）一键转成 Telegram 贴纸包，并可直接**全自动上传**到你自己的 Telegram 机器人创建的贴纸集。

纯本地 Web 工具（Flask），无需注册任何服务，跑起来就是一个网页。

---

## ✨ 功能

- **扫码即用**：选择文件夹，自动识别真实图片格式（按文件内容，扩展名写错也能用），并生成预览图。
- **一键生成**：静态图 → PNG（512px，>512KB 自动转 WebP）；动图 GIF → WEBM 视频贴纸（<3s）。
- **并行处理**：多核并行转码，全程显示实时进度。
- **全自动上传**：把生成的贴纸直接通过 Bot API 传到你的 Telegram 贴纸包，超过 120 张自动拆成多包，上传完毕后给出 `t.me/addstickers/xxx` 链接。
- **分包可勾选**：上传前可勾选要传哪几个分包（超 120 张拆成 第1包/第2包…）。
- **历史包复用**：之前生成过的包都存在本地磁盘 `work/`，可一键选历史包再次上传，无需重新生成。
- **备选手动流程**：也可下载 `stickers.zip` 发给 @Stickers 手工建包。

---

## 📦 环境要求

- Windows（本工具在 Windows 上开发测试）
- Python 3.9+
- ffmpeg（**仅动图转码需要**）：可执行系统里的 `ffmpeg`，或放到 `ffmpeg/bin/`，或 `C:\ffmpeg\bin\ffmpeg.exe`；没有也能生成静态贴纸，只是动图会被跳过。

依赖：

```
flask>=3.0
pillow>=10.0
requests>=2.31
pytest>=8.0   # 仅开发 / 测试需要
```

---

## 🚀 快速开始

1. **安装依赖**
   ```bat
   pip install -r requirements.txt
   ```

2. **配置你的 bot**（第一次用必做）：
   - 找 **@BotFather** 发 `/newbot` 建一个 bot，拿到 **token**；
   - 找 **@userinfobot** 发任意消息，得到你的 **数字用户 ID**；
   - **先给你自己的 bot 发一条 `/start`**（否则 Telegram 拒绝建贴纸包）。

3. **填写 `start.bat`**（把文件顶部 `set` 行等号右边换成你的值，`TG_BOT_NAME` 可留空，启动时会自动获取）：
   ```bat
   set "TG_BOT_TOKEN=你的token"
   set "TG_OWNER_ID=你的数字ID"
   set "TG_BOT_NAME=你的bot用户名"   & rem 可选，也可留空
   ```
   > ⚠️ 真实 token 只在本机 `start.bat` 里使用，改完后**不要** `git add` / 提交该文件。也可以改成设置系统环境变量，bat 里保持留空。

4. **双击 `start.bat`**，浏览器会自动打开 `http://127.0.0.1:5000`。

> ffmpeg 需要时：从 [ffmpeg 官网](https://www.gyan.dev/ffmpeg/builds/) 下载，把 `ffmpeg.exe`（和同目录的 exe）放到项目 `ffmpeg/bin/`，或保证命令行里能调用 `ffmpeg`。工具会自动检测。

---

## 🧭 使用步骤（Web 界面）

| 步骤 | 说明 |
|---|---|
| **① 选择文件夹** | 用「选择文件夹…」直接读本地文件（推荐），或粘贴磁盘路径后「按路径扫描」 |
| **② 勾选表情** | 网格预览，双击可放大，可按文件名筛选、全选/全不选 |
| **③ 生成贴纸包** | 填包名建议名 → 生成 `stickers.zip`，显示静态/动图数量，可下载 |
| **④ 全自动上传** | 勾选要上传的分包 → 「上传所选包」，进度实时显示，完成后给出添加链接 |
| **📦 从历史包上传** | 有历史包时出现独立按钮，弹窗里选历史包、勾选分包再上传，无需重新生成 |
| **⑤ 备选手动** | 把 zip 里的文件手工发给 @Stickers |

---

## 🤖 上传逻辑说明（给开发者）

- 单包上限 **120 张**；超过自动拆成 `xxx_by_bot`、`xxx_by_bot_2`、`xxx_by_bot_3`…
- `createNewStickerSet` 一次最多带 50 个贴纸（`attach://fN` + 文件），其余用 `addStickerToSet` 并发追加。
- 包名 short_name 由「前缀 + `_by_机器人用户名`」组成，字母开头，只含字母数字下划线。
- 名称冲突处理：整包上传时自动寻找一组「连续可用」的起始编号；部分分包上传时每个包独立向后顺延寻找空闲名。
- 429 / 5xx / 网络错误统一由 `telegram/client.py` 的 `tg_call` 退避重试（429 会读取 `retry_after`）。
- 通过 Bot API 创建的贴纸包即建即用、无需 `/publish`，但不会自动进贴纸面板，需通过 `t.me/addstickers/xxx` 添加一次。

---

## 📁 目录结构

```
weixinStickerToTelegram/
├── app.py               # 启动入口：app factory + 本地服务
├── weixin2tg/           # 业务包（模块化）
│   ├── config.py        # 路径常量、环境变量、启动诊断
│   ├── logging_setup.py # 统一日志（替代 print）
│   ├── routes/          # Flask 蓝图（无业务逻辑）
│   │   ├── pages.py     # 首页 + 预览图
│   │   ├── scan.py      # /api/scan、/api/scan_upload
│   │   ├── build.py     # /api/build、/api/status/<id>、/api/download/<id>、/api/ffmpeg-check
│   │   ├── history.py   # /api/history
│   │   └── upload.py    # /api/upload（含 history_id）、/api/preset
│   ├── services/        # 纯业务逻辑（无 Flask 依赖）
│   │   ├── scanner.py   # 按内容识别格式、文件夹扫描、预览生成
│   │   ├── converter.py # 静态 PNG/WebP、动图 WEBM、ffmpeg 发现
│   │   ├── packer.py    # README + zip 打包
│   │   ├── jobs.py      # Job 状态机、构建/上传 worker、清理线程
│   │   └── history.py   # work/ 目录历史包索引（30s 缓存）
│   └── telegram/        # Telegram Bot API 客户端
│       ├── client.py    # tg_call：超时/重试/错误归一（TgError）
│       ├── sticker.py   # make_pack_name、占用检查、连续区间查找
│       └── uploader.py  # 分包命名规划 → 创建 → 并发追加
├── templates/
│   └── index.html       # 单页界面
├── static/
│   ├── style.css        # 现代化 UI 样式
│   └── app.js           # 前端交互逻辑
├── tests/               # pytest 测试（scan→build→history→upload 全链路）
│   ├── conftest.py
│   ├── test_scanner.py
│   ├── test_converter.py
│   ├── test_sticker.py
│   ├── test_jobs.py
│   └── test_api_e2e.py
├── requirements.txt
├── start.bat            # 一键启动（token 占位，需自行填写）
├── work/                # 运行产物（预览、上传缓存、job 包）——已在 .gitignore 忽略
└── ffmpeg/              # 可选：内嵌 ffmpeg（体积大，勿提交 Git）
```

---

## ⚙️ 主要 API

| 接口 | 方法 | 说明 |
|---|---|---|
| `/api/scan` | POST | 按磁盘路径扫描文件夹 `{folder}` → `{items}` |
| `/api/scan_upload` | POST | 「选择文件夹」方式上传：落盘后立即返回 `{job_id, count}`，识别/预览在后台任务执行，轮询 `/api/status/<id>` 到 done 后从 `results.items` 取文件列表 |
| `/api/build` | POST | 启动贴纸包生成（后台线程）`{items, pack_name}` → `{job_id}` |
| `/api/status/<id>` | GET | 轮询任务进度（`state/percent/message/error/results`） |
| `/api/download/<id>` | GET | 下载生成的 stickers.zip |
| `/api/history` | GET | 列出历史生成的包 `{items: [{id, time, static, anim}]}` |
| `/api/upload` | POST | 全自动上传：`job_id`（本次生成）或 `history_id`（历史包）二选一 |
| `/api/preset` | GET | 读取环境变量配置状态 `{has_token, owner_id, bot_name}` |
| `/api/ffmpeg-check` | GET | 检查 ffmpeg 是否可用 |

item 字段：`{id, name, path, kind, size, preview}`；`kind` 为 `static` 或 `gif`（按内容识别）。

---

## 🧪 测试

```bat
pip install -r requirements.txt
pytest
```

测试会：
- 用 Flask `test_client` 走通 `scan_upload → build → 轮询 → 下载 zip → history → upload` 全链路；
- Telegram 网络层通过 mock `client.tg_call` 注入，不会真正请求 Telegram；
- 运行产物写入独立的临时目录（通过 `WX2TG_WORK_DIR` 环境变量隔离），不影响真实 `work/`。

---

## 🔒 安全提示

- **Token 是敏感凭证**：`start.bat` 请用占位符或你自己的值，**不要**把真实 token 提交到公开 GitHub。
  （此前提交到仓库历史里的旧 token 建议到 @BotFather 用 `/revoke` 作废重置。）
- 本工具仅监听 `127.0.0.1`，只允许本机访问，不会对外开放端口。

---

## 🧾 License

MIT — 自由使用、修改、二次发布。详见仓库 LICENSE（如未提供，按 MIT 精神使用即可）。
