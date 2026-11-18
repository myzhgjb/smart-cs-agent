#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
if [ ! -x ".venv/Scripts/python.exe" ]; then
  echo "未找到虚拟环境，请先创建并安装依赖："
  echo "  python -m venv .venv"
  echo "  .venv/Scripts/python.exe -m pip install -r requirements.txt -i https://mirrors.cloud.tencent.com/pypi/simple"
  exit 1
fi
exec .venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
