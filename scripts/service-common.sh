#!/bin/bash
#
# 本地服务脚本共用函数
#

service_port() {
    case "$1" in
        web) echo 3001 ;;
        server) echo 8080 ;;
        agent) echo 8000 ;;
        rank) echo 5001 ;;
        *)
            return 1
            ;;
    esac
}

service_pidfile() {
    echo ".pids/$1.pid"
}

service_listen_pids() {
    local name=$1
    local port
    port=$(service_port "$name") || return 1
    lsof -nP -t -iTCP:"$port" -sTCP:LISTEN 2>/dev/null | sort -u
}

