#!/bin/bash

# 加载环境变量
set -a
source .env
set +a

# 启动应用
# exec uvicorn main:app --host 0.0.0.0 --port 8003
exec gunicorn -w 4 -b 0.0.0.0:5001 app:app