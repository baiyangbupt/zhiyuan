# 多阶段构建 - 构建阶段
FROM docker.m.daocloud.io/library/python:3.12-slim AS builder

WORKDIR /build

# 安装构建依赖
RUN pip install --no-cache-dir --upgrade pip setuptools wheel -i https://pypi.tuna.tsinghua.edu.cn/simple

# 复制项目文件
COPY pyproject.toml ./
COPY app ./app
COPY skills ./skills

# 构建 wheel 包
RUN pip wheel --no-cache-dir --no-deps --wheel-dir /build/wheels . -i https://pypi.tuna.tsinghua.edu.cn/simple

# 运行阶段
FROM docker.m.daocloud.io/library/python:3.12-slim

WORKDIR /app

# 创建非 root 用户
RUN useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app

# 从构建阶段复制 wheel 包
COPY --from=builder /build/wheels /tmp/wheels
COPY --from=builder /build/pyproject.toml .

# 安装依赖和应用
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir /tmp/wheels/*.whl && \
    rm -rf /tmp/wheels

# 复制应用代码和技能目录
COPY --chown=appuser:appuser app ./app
COPY --chown=appuser:appuser skills ./skills

# 切换到非 root 用户
USER appuser

# 暴露端口
EXPOSE 8009

# 启动命令
CMD ["uvicorn", "app.server:app", "--host", "0.0.0.0", "--port", "8009"]
