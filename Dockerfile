# Multi-arch friendly: python:3.12-slim has amd64 + arm64 variants,
# so `docker compose build` works on x86 and ARM NAS boxes alike.
FROM python:3.12-slim

WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

RUN mkdir -p /data/photos

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
