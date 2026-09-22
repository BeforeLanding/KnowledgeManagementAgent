FROM python:3.12-slim
WORKDIR /workspace
COPY pyproject.toml ./
RUN pip install --no-cache-dir uv && uv pip install --system .
COPY services/api ./services/api
WORKDIR /workspace/services/api
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

