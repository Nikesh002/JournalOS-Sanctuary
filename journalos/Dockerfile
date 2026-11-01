# Copyright 2026 Google LLC
# Licensed under the Apache License, Version 2.0

FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.8.13 /uv /uvx /bin/

WORKDIR /code

COPY ./pyproject.toml ./README.md ./uv.lock* ./
COPY ./app ./app
COPY ./frontend ./frontend
COPY ./scripts ./scripts

RUN uv sync --frozen

EXPOSE 8080

CMD ["uv", "run", "uvicorn", "frontend.main:app", "--host", "0.0.0.0", "--port", "8080"]
