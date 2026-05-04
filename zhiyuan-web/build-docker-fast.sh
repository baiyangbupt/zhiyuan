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
IMAGE_NAME="zhiyuan-web"
REGISTRY="crpi-zmigon88wuzuzy3k.cn-hangzhou.personal.cr.aliyuncs.com"
REPOSITORY="gt_test_123"

REMOTE_IMAGE="${REGISTRY}/${REPOSITORY}/${IMAGE_NAME}:${IMAGE_TAG}"

# 执行构建前的准备工作
echo "开始执行构建前的准备工作..."

# 安装依赖
echo "正在执行: npm install"
npm install
if [ $? -ne 0 ]; then
    echo "❌ 错误: npm install 执行失败"
    exit 1
fi
echo "✅ npm install 执行成功"

# 执行构建
echo "正在执行: npm run build:${ENV}"
npm run build:${ENV}
if [ $? -ne 0 ]; then
    echo "❌ 错误: npm run build:${ENV} 执行失败"
    exit 1
fi
echo "✅ npm run build:${ENV} 执行成功"

# 验证构建产物是否存在
echo "检查构建产物..."
if [[ ! -d ".next" ]]; then
    echo "❌ 错误: 找不到 .next 目录"
    echo "请先运行构建命令，例如: npm run build:${ENV}"
    exit 1
fi

if [[ ! -d "node_modules" ]]; then
    echo "❌ 错误: 找不到 node_modules 目录"
    echo "请先运行: npm install"
    exit 1
fi

echo "✅ 构建产物检查通过"

# 创建 BuildKit 缓存目录 - 保持与原有脚本一致
mkdir -p ~/.docker/buildkit-cache

# 构建 Docker 镜像
echo "开始快速构建 Docker 镜像..."
echo "环境: $ENV"
echo "版本: $VERSION"
echo "镜像标签: $IMAGE_TAG"
echo "完整镜像名: $REMOTE_IMAGE"

# 启用buildx - 保持与原有脚本一致
echo "配置 docker buildx..."
docker buildx create --name fast-builder --use 2>/dev/null || docker buildx use fast-builder

echo "开始构建Linux平台Docker镜像..."
echo "构建并推送Linux平台Docker镜像..."

# 使用快速 Dockerfile 进行构建
DOCKER_BUILDKIT=1 docker buildx build --platform linux/amd64 \
    --build-arg APP_ENV=$ENV \
    --cache-from type=local,src=~/.docker/buildkit-cache \
    --cache-to type=local,dest=~/.docker/buildkit-cache \
    -f Dockerfile.fast \
    -t ${REMOTE_IMAGE} \
    --push .

BUILD_RESULT=$?

if [ $BUILD_RESULT -eq 0 ]; then
    echo "✅ Docker镜像快速构建并推送成功"
    echo "已推送的镜像标签:"
    echo "- ${REMOTE_IMAGE}"
    echo "支持的平台: linux/amd64"
    echo ""
    echo "🚀 部署命令参考:"
    echo "docker run -d -p 28688:28688 --name zhiyuan-web-${ENV} ${REMOTE_IMAGE}"
    echo ""
    echo "📝 查看日志:"
    echo "docker logs -f zhiyuan-web-${ENV}"
else
    echo "❌ Docker镜像构建失败"
    exit 1
fi 