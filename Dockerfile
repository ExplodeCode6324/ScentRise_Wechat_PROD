# ScentRise PROD Dockerfile
# 目标平台：腾讯云 CloudRun（微信云托管）
# 基础镜像：Alpine 3.19（Python 3.11，LTS 支持至 2025-11）
FROM alpine:3.19

# ============================================
# 系统层：时区 + CA 证书 + Python
# ============================================
RUN set -ex \
    && apk add --no-cache tzdata ca-certificates python3 py3-pip \
    && cp /usr/share/zoneinfo/Asia/Shanghai /etc/localtime \
    && echo "Asia/Shanghai" > /etc/timezone \
    && apk del tzdata \
    && rm -rf /var/cache/apk/*

# ============================================
# 依赖层：先装 pip 包（利用 Docker 缓存，代码变更无需重装依赖）
# greenlet 3.1.1+ 有 musllinux 预编译包，无需 gcc
# ============================================
WORKDIR /app
COPY requirements.txt .

RUN pip config set global.index-url http://mirrors.cloud.tencent.com/pypi/simple \
    && pip config set global.trusted-host mirrors.cloud.tencent.com \
    && pip install --no-cache-dir --upgrade pip --break-system-packages \
    && pip install --no-cache-dir -r requirements.txt --break-system-packages

# ============================================
# 代码层
# ============================================
COPY . .

# ============================================
# 运行时配置
# ============================================
EXPOSE 80

# 健康检查：CloudRun 用它判断容器是否就绪
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:80/api/categories')" || exit 1

CMD ["python3", "run.py", "0.0.0.0", "80"]
