#!/bin/bash

# 快速 Docker 构建脚本 - 适用于本地已构建的项目
# 基于原有 build-docker.sh 的配置和逻辑

# 检查是否提供了环境参数和版本号
if [ -z "$1" ] || [ -z "$2" ]; then
    echo "错误：请指定环境参数和版本号"
    echo "使用方法: ./build-docker-fast.sh <环境> <版本号>"
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

# 验证环境参数并设置镜像标签 - 保持与原有脚本一致
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

# 设置镜像名称和远程仓库地址 - 保持与原有脚本一致
IMAGE_NAME="zhiyuan-rank"
REGISTRY="crpi-zmigon88wuzuzy3k.cn-hangzhou.personal.cr.aliyuncs.com"
REPOSITORY="gt_test_123"

REMOTE_IMAGE="${REGISTRY}/${REPOSITORY}/${IMAGE_NAME}:${IMAGE_TAG}"

# 执行构建前的准备工作
echo "开始执行构建前的准备工作..."


# 构建 Docker 镜像
echo "开始快速构建 Docker 镜像..."
echo "环境: $ENV"
echo "版本: $VERSION"
echo "镜像标签: $IMAGE_TAG"
echo "完整镜像名: $REMOTE_IMAGE"

# 启用buildx
echo "配置 docker buildx..."
docker buildx create --use

echo "开始构建Linux平台Docker镜像..."
echo "构建并推送Linux平台Docker镜像..."
docker buildx build --platform linux/amd64 \
    --build-arg ENV=${ENV} \
    -f Dockerfile.fast \
    -t ${REMOTE_IMAGE} \
    --push .

if [ $? -eq 0 ]; then
    echo "✅ Docker镜像快速构建并推送成功"
    echo "已推送的镜像标签:"
    echo "- ${REMOTE_IMAGE}"
    echo "支持的平台: linux/amd64"
else
    echo "❌ Docker镜像构建失败"
    exit 1
fi 