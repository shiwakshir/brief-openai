# BRIEF: single-process web app. Sessions live in memory, so run exactly one worker.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p runs && useradd --create-home brief && chown -R brief /app
USER brief

EXPOSE 8000
HEALTHCHECK CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')" || exit 1
CMD ["gunicorn", "-w", "1", "--threads", "8", "--timeout", "1000", "-b", "0.0.0.0:8000", "app:app"]
