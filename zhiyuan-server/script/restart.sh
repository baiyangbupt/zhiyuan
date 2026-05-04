#!/bin/bash
# 获取进程 ID
tpid=$(cat tpid  2>/dev/null)
if [ -z "$tpid" ]; then
    echo "Application is not running. Starting the application..."
    sh start.sh
    echo "Application started."
else
    sh stop.sh
    # 等待应用程序停止
    while ps -p "$tpid" >/dev/null; do
        sleep 1
    done
    echo "Application stopped."
    # 清除 tpid 文件
    rm -f tpid
    echo "Starting the application..."
    sh start.sh
    echo "Application started."
fi

app_name=zhiyuan-server

tail -f logs/$app_name.log