# Backend: una imagen, dos comandos (api | worker) — un proceso por contenedor.
# Gestor recomendado: `uv` (fallback pip/venv documentado abajo).
FROM python:3.12.7-slim-bookworm AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/srv/app/backend

WORKDIR /srv/app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./backend/
COPY alembic.ini ./

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://localhost:8000/ready')"

# Por defecto sirve la API; el worker sobrescribe el comando en Compose.
# C-14 (D2): sin access log de uvicorn (imprime el path real, que en /api/manage/{token} lleva el
# token); lo reemplaza el log de acceso redactado del middleware de contexto.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
