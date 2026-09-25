FROM python:3.14-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DATA_DIR=/app/data \
    PORT=8792

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && python -m playwright install-deps firefox \
    && python -m camoufox fetch \
    && rm -rf /var/lib/apt/lists/*

COPY signal_nas ./signal_nas
COPY config ./config
RUN mkdir -p /app/data

EXPOSE 8792
CMD ["python", "-m", "signal_nas"]
