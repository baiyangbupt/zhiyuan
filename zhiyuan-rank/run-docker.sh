#!/bin/bash

# 检查是否提供了环境参数和版本号
if [ -z "$1" ] || [ -z "$2" ]; then
    echo "错误：请指定环境参数和版本号"
    echo "使用方法: ./run-docker.sh <环境> <版本号>"
    echo "可用环境: dev, test, prod"
    echo "版本号格式: x.y.z (例如: 1.0.0)"
    exit 1
fi

# 设置环境变量
ENV=$1
VERSION=$2

# 验证版本号格式
if ! [[ $VERSION =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "错误：版本号格式不正确"
    echo "版本号格式应为: x.y.z (例如: 1.0.0)"
    exit 1
fi

case $ENV in
    "dev")
        IMAGE_TAG="dev-${VERSION}"
        ;;
    "test")
        IMAGE_TAG="test-${VERSION}"
        ;;
    "prod")
        IMAGE_TAG="prod-${VERSION}"
        ;;
    *)
        echo "错误：无效的环境参数"
        echo "可用环境: dev, test, prod"
        exit 1
        ;;
esac

# 设置镜像名称和远程仓库地址
IMAGE_NAME="zhiyuan-rank"
REGISTRY="crpi-zmigon88wuzuzy3k.cn-hangzhou.personal.cr.aliyuncs.com"
REPOSITORY="gt_test_123"

REMOTE_IMAGE="${REGISTRY}/${REPOSITORY}/${IMAGE_NAME}:${IMAGE_TAG}"
CONTAINER_NAME="zhiyuan-rank-${ENV}"
PORT=8092

# 从远程仓库拉取镜像
echo "正在从远程仓库拉取镜像..."
docker pull ${REMOTE_IMAGE}

# 检查拉取是否成功
if [ $? -ne 0 ]; then
    echo "镜像拉取失败！请确保镜像已经构建并推送到远程仓库。"
    exit 1
fi

# 检查容器是否已经存在
if [ "$(docker ps -aq -f name=${CONTAINER_NAME})" ]; then
    echo "发现已存在的容器，正在停止并删除..."
    docker stop ${CONTAINER_NAME}
    docker rm ${CONTAINER_NAME}
fi

# 运行新的容器
echo "正在启动 Docker 容器..."
echo "环境: $ENV"
echo "版本: $VERSION"
echo "端口: $PORT"
# 检查logs目录是否存在，不存在则创建
if [ ! -d "logs" ]; then
    echo "创建logs目录..."
    mkdir logs
fi

docker run -d \
    --name ${CONTAINER_NAME} \
    -v $(pwd)/logs:/app/logs \
    -p ${PORT}:5001 \
    -e APP_ENV=${ENV} \
    ${REMOTE_IMAGE} \

# 检查容器是否成功启动
if [ $? -eq 0 ]; then
    echo "Docker 容器启动成功！"
    echo "容器名称: ${CONTAINER_NAME}"
    echo "访问地址: http://localhost:${PORT}"
else
    echo "Docker 容器启动失败！"
    exit 1
fi 

# 显示容器日志
echo "📝 显示容器日志..."
docker logs -f ${CONTAINER_NAME}