@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo [错误] 未找到虚拟环境，请先执行：
  echo   python -m venv .venv
  echo   .venv\Scripts\python.exe -m pip install -r requirements.txt -i https://mirrors.cloud.tencent.com/pypi/simple
  pause
  exit /b 1
)
echo ============================================
echo   星海优选 · 智能客服系统
echo   客服端 http://127.0.0.1:8000
echo   管理台 http://127.0.0.1:8000/admin
echo ============================================
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
pause
