# Dockerfile - Hermes 报告服务器
FROM python:3.11-slim

WORKDIR /app

# 安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY . .

# 创建报告目录
RUN mkdir -p /app/reports /app/templates/hermes

# 暴露端口
EXPOSE 8000

# 默认命令
CMD ["python", "report_server.py"]
