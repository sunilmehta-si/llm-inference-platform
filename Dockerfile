# The base image by digest, so every build starts from the same bytes; Dependabot moves the digest (docker
# ecosystem, after its 14-day cooldown) when python:3.13-slim is rebuilt.
FROM python:3.13-slim@sha256:7249d5587b78209a006dc4a3b5340678f84ea729239193aa559962cd8c1fce50
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml ./
COPY requirements-tested.txt ./
COPY gateway ./gateway
RUN pip install --no-cache-dir -c requirements-tested.txt . && useradd --uid 10001 --create-home inference
USER 10001
EXPOSE 8000
CMD ["uvicorn", "gateway.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
