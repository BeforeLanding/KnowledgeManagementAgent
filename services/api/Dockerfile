FROM python:3.12-slim
WORKDIR /workspace
COPY pyproject.toml ./
COPY alembic.ini ./
RUN pip install --no-cache-dir uv && uv pip install --system .
RUN addgroup --system kma && adduser --system --ingroup kma kma
COPY --chown=kma:kma services/api ./services/api
WORKDIR /workspace/services/api
USER kma
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health/live', timeout=3)"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
