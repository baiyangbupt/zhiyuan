#!/bin/bash

# 检查是否提供了环境参数和版本号
if [ -z "$1" ] || [ -z "$2" ]; then
    echo "错误：请指定环境参数和版本号"
    echo "使用方法: ./build-docker.sh <环境> <版本号>"
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
IMAGE_NAME="zhiyuan-web"
REGISTRY="crpi-zmigon88wuzuzy3k.cn-hangzhou.personal.cr.aliyuncs.com"
REPOSITORY="gt_test_123"

REMOTE_IMAGE="${REGISTRY}/${REPOSITORY}/${IMAGE_NAME}:${IMAGE_TAG}"

# 创建 BuildKit 缓存目录
mkdir -p ~/.docker/buildkit-cache

# 构建 Docker 镜像
echo "开始构建 Docker 镜像..."
echo "环境: $ENV"
echo "版本: $VERSION"
echo "镜像标签: $IMAGE_TAG"

# 启用buildx
echo "配置 docker buildx..."
docker buildx create --use

echo "开始构建Linux平台Docker镜像..."
echo "构建并推送Linux平台Docker镜像..."

DOCKER_BUILDKIT=1 docker buildx build --platform linux/amd64 \
    --build-arg APP_ENV=$ENV \
    --cache-from type=local,src=~/.docker/buildkit-cache \
    --cache-to type=local,dest=~/.docker/buildkit-cache \
    -t ${REMOTE_IMAGE} \
    --push .

if [ $? -eq 0 ]; then
    echo "✅ Docker镜像构建并推送成功"
    echo "已推送的镜像标签:"
    echo "-${REMOTE_IMAGE}"
    echo "支持的平台: linux/amd64"
else
    echo "❌ Docker镜像构建失败"
    exit 1
fi