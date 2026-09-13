FROM python:3.12.9-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --no-compile -r requirements.txt

COPY . .
RUN mkdir -p /app/runs && useradd --create-home --uid 10001 brief && chown -R brief:brief /app
USER 10001:10001

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=3)" || exit 1
CMD ["gunicorn", "-w", "1", "--threads", "8", "--timeout", "1000", "--access-logfile", "-", "--error-logfile", "-", "-b", "0.0.0.0:8000", "app:app"]
