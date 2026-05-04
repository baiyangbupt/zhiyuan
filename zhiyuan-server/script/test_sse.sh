#!/bin/bash

# SSE测试脚本 - 中文显示测试版
# 用于测试SSE连接中文数据显示是否正常

# 配置
DEFAULT_HOST="localhost"
DEFAULT_PORT="8090"
DEFAULT_SESSION_ID="1"
TIMEOUT=300  # 5分钟超时

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# 打印带颜色的消息
print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_event() {
    echo -e "${PURPLE}[EVENT]${NC} $1"
}

print_heartbeat() {
    echo -e "${CYAN}[HEARTBEAT]${NC} $1"
}

print_data() {
    echo -e "${GREEN}[数据]${NC} $1"
}

# 显示帮助信息
show_help() {
    echo "SSE中文显示测试脚本"
    echo "用于测试SSE连接中文数据是否乱码"
    echo ""
    echo "用法: $0 [选项]"
    echo ""
    echo "选项:"
    echo "  -h, --host HOST        服务器地址 (默认: $DEFAULT_HOST)"
    echo "  -p, --port PORT        服务器端口 (默认: $DEFAULT_PORT)"
    echo "  -s, --session SESSION  会话ID (默认: $DEFAULT_SESSION_ID)"
    echo "  -t, --timeout TIMEOUT  连接超时秒数 (默认: $TIMEOUT)"
    echo "  -x, --hex              显示十六进制数据用于诊断编码"
    echo "  --help                 显示此帮助信息"
    echo ""
    echo "示例:"
    echo "  $0                                    # 使用默认配置"
    echo "  $0 -h localhost -p 8090 -s 1         # 指定参数"
    echo "  $0 -x                                # 显示十六进制数据"
    echo "  $0 -h 127.0.0.1 -s 2 -t 600          # 指定主机、会话ID和超时时间"
}

# 解析命令行参数
parse_args() {
    HOST="$DEFAULT_HOST"
    PORT="$DEFAULT_PORT"
    SESSION_ID="$DEFAULT_SESSION_ID"
    SHOW_HEX="false"
    
    while [[ $# -gt 0 ]]; do
        case $1 in
            -h|--host)
                HOST="$2"
                shift 2
                ;;
            -p|--port)
                PORT="$2"
                shift 2
                ;;
            -s|--session)
                SESSION_ID="$2"
                shift 2
                ;;
            -t|--timeout)
                TIMEOUT="$2"
                shift 2
                ;;
            -x|--hex)
                SHOW_HEX="true"
                shift
                ;;
            --help)
                show_help
                exit 0
                ;;
            *)
                print_error "未知参数: $1"
                show_help
                exit 1
                ;;
        esac
    done
}

# 验证参数
validate_args() {
    if ! [[ "$PORT" =~ ^[0-9]+$ ]] || [ "$PORT" -lt 1 ] || [ "$PORT" -gt 65535 ]; then
        print_error "无效的端口号: $PORT"
        exit 1
    fi
    
    if ! [[ "$SESSION_ID" =~ ^[0-9]+$ ]] || [ "$SESSION_ID" -lt 1 ]; then
        print_error "无效的会话ID: $SESSION_ID"
        exit 1
    fi
    
    if ! [[ "$TIMEOUT" =~ ^[0-9]+$ ]] || [ "$TIMEOUT" -lt 1 ]; then
        print_error "无效的超时时间: $TIMEOUT"
        exit 1
    fi
}

# 检查服务器是否可达
check_server() {
    print_info "检查服务器连通性..."
    
    if ! command -v curl &> /dev/null; then
        print_error "curl命令未找到，请安装curl"
        exit 1
    fi
    
    # 检查端口是否开放
    if ! timeout 5 bash -c "</dev/tcp/$HOST/$PORT" 2>/dev/null; then
        print_error "无法连接到 $HOST:$PORT"
        print_info "请检查:"
        echo "  - 服务是否启动"
        echo "  - 端口是否正确"
        echo "  - 防火墙设置"
        exit 1
    fi
    
    print_success "服务器 $HOST:$PORT 可达"
}

# 测试SSE状态接口
test_status_api() {
    local status_url="http://$HOST:$PORT/gaotu-assistant-bot/sse/asr/status/$SESSION_ID"
    print_info "测试状态接口: $status_url"
    
    local response=$(curl -s -w "\n%{http_code}" --connect-timeout 10 "$status_url")
    local http_code=$(echo "$response" | tail -n1)
    local body=$(echo "$response" | head -n -1)
    
    if [ "$http_code" = "200" ]; then
        print_success "状态接口正常 (HTTP $http_code)"
        if [ ! -z "$body" ]; then
            print_data "响应内容: $body"
        fi
    else
        print_warning "状态接口响应异常 (HTTP $http_code)"
        if [ ! -z "$body" ]; then
            print_data "响应内容: $body"
        fi
    fi
}

# 主要的SSE连接测试
test_sse_connection() {
    local sse_url="http://$HOST:$PORT/gaotu-assistant-bot/sse/asr/connect/$SESSION_ID"
    local start_time=$(date +%s)
    local event_count=0
    local heartbeat_count=0
    local data_count=0
    local connected=false
    
    print_info "开始SSE连接测试"
    print_info "URL: $sse_url"
    print_info "会话ID: $SESSION_ID"
    print_info "超时时间: ${TIMEOUT}秒"
    print_info "开始时间: $(date '+%Y-%m-%d %H:%M:%S')"
    print_info "等待接收中文数据..."
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    
    # 清理函数
    cleanup() {
        local end_time=$(date +%s)
        local duration=$((end_time - start_time))
        echo ""
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        print_info "连接统计:"
        echo "  - 连接持续时间: ${duration}秒"
        echo "  - 收到事件总数: $event_count"
        echo "  - 收到数据消息: $data_count"
        echo "  - 心跳消息数量: $heartbeat_count"
        echo "  - 连接状态: $([ "$connected" = true ] && echo "已连接" || echo "未连接")"
        echo "  - 结束时间: $(date '+%Y-%m-%d %H:%M:%S')"
    }
    
    # 设置信号处理
    trap cleanup EXIT INT TERM
    
    # 启动curl SSE连接并实时处理
    print_info "正在建立SSE连接..."
    
    curl -N -s \
        --connect-timeout 10 \
        --max-time "$TIMEOUT" \
        -H "Accept: text/event-stream" \
        -H "Cache-Control: no-cache" \
        "$sse_url" | while IFS= read -r line; do
        
        current_time=$(date +%s)
        duration=$((current_time - start_time))
        timestamp=$(date '+%H:%M:%S')
        
        # 解析SSE事件
        if [[ "$line" =~ ^event:(.+) ]]; then
            local event_type="${BASH_REMATCH[1]// /}"
            event_count=$((event_count + 1))
            
            case "$event_type" in
                "connected")
                    print_success "[$timestamp] ✅ 连接建立成功"
                    connected=true
                    ;;
                "heartbeat")
                    heartbeat_count=$((heartbeat_count + 1))
                    print_heartbeat "[$timestamp] 💓 心跳 #$heartbeat_count"
                    ;;
                "asr_content")
                    print_event "[$timestamp] 📝 收到ASR内容事件"
                    ;;
                "disconnected")
                    print_warning "[$timestamp] 🔌 连接断开"
                    connected=false
                    ;;
                "error")
                    print_error "[$timestamp] ❌ 收到错误事件"
                    ;;
                *)
                    print_event "[$timestamp] 📬 事件类型: $event_type"
                    ;;
            esac
                 elif [[ "$line" =~ ^data:(.+) ]]; then
             local data="${BASH_REMATCH[1]}"
             data_count=$((data_count + 1))
             
             # 直接显示数据内容，不做任何转换
             print_data "[$timestamp] 接收数据 #$data_count:"
             echo "     内容: $data"
             echo "     长度: ${#data} 字符"
             
             # 检查是否包含问号（可能的乱码）
             if [[ "$data" =~ \? ]]; then
                 print_warning "     检测到问号字符，可能存在编码问题！"
             fi
             
             # 如果启用了十六进制显示
             if [ "$SHOW_HEX" = "true" ]; then
                 if command -v xxd &> /dev/null; then
                     echo "     十六进制:"
                     echo -n "$data" | xxd | sed 's/^/       /'
                 else
                     echo "     十六进制: xxd命令不可用"
                 fi
             fi
             
             # 如果包含JSON，尝试格式化显示
             if [[ "$data" =~ ^\{.*\}$ ]]; then
                 if command -v jq &> /dev/null; then
                     echo "     格式化:"
                     echo "$data" | jq . 2>/dev/null | sed 's/^/       /' || echo "       JSON格式化失败"
                 fi
             fi
             echo ""
        elif [ ! -z "$line" ] && [[ ! "$line" =~ ^: ]]; then
            # 显示其他非空行（排除注释行）
            echo "[$timestamp] 原始数据: $line"
            echo ""
        fi
    done
    
    # 检查curl退出状态
    local curl_exit_code=$?
    
    if [ "$curl_exit_code" -ne 0 ]; then
        case "$curl_exit_code" in
            7)
                print_error "连接被拒绝 (curl退出码: $curl_exit_code)"
                ;;
            28)
                print_error "连接超时 (curl退出码: $curl_exit_code)"
                ;;
            52)
                print_error "服务器返回空响应 (curl退出码: $curl_exit_code)"
                ;;
            *)
                print_error "curl异常退出 (退出码: $curl_exit_code)"
                ;;
        esac
    fi
}

# 主函数
main() {
    echo "======================================"
    echo "      SSE中文显示测试脚本"
    echo "======================================"
    echo ""
    
    parse_args "$@"
    validate_args
    
    print_info "测试参数:"
    echo "  - 服务器: $HOST:$PORT"
    echo "  - 会话ID: $SESSION_ID"
    echo "  - 超时时间: ${TIMEOUT}秒"
    echo "  - 十六进制显示: $SHOW_HEX"
    echo ""
    
    check_server
    test_status_api
    echo ""
    test_sse_connection
    
    echo ""
    print_info "测试完成"
    echo ""
    print_info "如果看到中文乱码，可能的原因："
    echo "  1. 后端未正确设置UTF-8编码"
    echo "  2. nginx未正确处理编码"
    echo "  3. 终端不支持UTF-8显示"
    echo "  4. 数据传输过程中编码被改变"
}

# 运行主函数
main "$@" 