@echo off
setlocal
cd /d "%~dp0"
rem ============================================================
rem  配置你的 Telegram bot（首次运行必做，把下面几行改成你的值）：
rem  - TG_BOT_TOKEN：向 @BotFather 发 /newbot 拿到的 token
rem  - TG_OWNER_ID：向 @userinfobot 发任意消息得到的你的数字 ID
rem  - TG_BOT_NAME：（可选）你的 bot 用户名，留空则启动时自动获取
rem
rem  ⚠️ 本文件会被提交到仓库：真实 token 只在本机填写使用，
rem     不要把它 commit 上去；也可设置系统环境变量、此处留空。
rem ============================================================
set "TG_BOT_TOKEN="
set "TG_OWNER_ID="

rem Optional: bot username，不填则启动时自动从 getMe 获取
set "TG_BOT_NAME="

rem 内嵌 ffmpeg：把项目自带 ffmpeg 加入 PATH（可选，用于动图转码）
if exist "%~dp0ffmpeg\bin" set "PATH=%~dp0ffmpeg\bin;%PATH%"

echo Checking dependencies...
python -c "import flask, PIL, requests" >nul 2>&1
if errorlevel 1 (
  echo Installing dependencies...
  pip install -r requirements.txt
)

echo Starting server, browser will open http://127.0.0.1:5000
python app.py
pause
endlocal
