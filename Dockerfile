FROM python:3.14-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml ./
COPY requirements-tested.txt ./
COPY gateway ./gateway
RUN pip install --no-cache-dir -c requirements-tested.txt . && useradd --uid 10001 --create-home inference
USER 10001
EXPOSE 8000
CMD ["uvicorn", "gateway.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
