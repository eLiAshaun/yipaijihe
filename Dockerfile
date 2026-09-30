FROM python:3.11-slim

# ffmpeg：视频转写切片需要（不用视频分析可以去掉这一行以减小镜像）
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# SQLite 放在挂载卷里，容器重启不丢数据
ENV DB_PATH=/data/luvdazi.db \
    FLASK_PORT=8080 \
    PYTHONUNBUFFERED=1
RUN mkdir -p /data
VOLUME /data
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8080/api/health')"

# 视频分析是长请求（1–2 分钟），timeout 需要放宽；单 worker 多线程，避免 SQLite 多进程争用
CMD ["sh", "-c", "gunicorn 'app:create_app()' --bind 0.0.0.0:${PORT:-8080} --workers 1 --threads 8 --timeout 300"]
