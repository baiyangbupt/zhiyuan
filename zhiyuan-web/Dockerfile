# 1. 基础镜像阶段
FROM --platform=linux/amd64 docker.m.daocloud.io/library/node:22.14.0 AS builder
# 设置工作目录
WORKDIR /app

# 2. 安装依赖阶段
FROM builder AS install

# 配置 npm 使用 npmmirror 镜像源
RUN npm config set registry https://registry.npmmirror.com/
RUN npm config set cache /root/.npm-cache --global

# 首先只复制 package.json 和 package-lock.json
COPY package*.json ./

# 使用 npm install 安装依赖，添加优化参数
RUN --mount=type=cache,target=/root/.npm-cache \
    npm install --prefer-offline --no-audit --no-fund --no-package-lock

# 3. 基于基础镜像进行最终构建
FROM builder
# 设置构建参数
ARG APP_ENV=dev
ARG NODE_ENV=production
# 设置环境变量
ENV APP_ENV=${APP_ENV}
ENV NODE_ENV=${NODE_ENV}

# 复制依赖和 package.json
COPY --from=install /app/node_modules ./node_modules
COPY --from=install /app/package*.json ./

# 复制源代码和环境变量文件，排除 node_modules
COPY src/ ./src/
COPY public/ ./public/
COPY .env* ./
COPY tsconfig.json ./
COPY next.config.mjs ./
COPY next-env.d.ts ./
COPY source-map.js ./

# 构建应用
RUN --mount=type=cache,target=/root/.npm-cache \
    npm run build:${APP_ENV}

# 暴露端口
EXPOSE 28688

# 启动命令
CMD npm run server:${APP_ENV} 
