FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /opt/portfolio
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && mkdir -p /home/container/data && chown -R 1000:1000 /home/container
COPY app.py index.html ./
USER 1000:1000
WORKDIR /home/container
EXPOSE 8080
CMD ["python", "-u", "/opt/portfolio/app.py"]
