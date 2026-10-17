# Build from repo root: docker build -f api/Dockerfile -t loopcloser-api .
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8080 APP_ENV=production
WORKDIR /app
COPY api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY api/loopcloser ./loopcloser
RUN useradd --system --uid 10001 app
USER app
EXPOSE 8080
CMD exec uvicorn loopcloser.main:create_app --factory --host 0.0.0.0 --port ${PORT} --proxy-headers --no-access-log
