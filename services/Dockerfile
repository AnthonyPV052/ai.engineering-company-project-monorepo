FROM python:3.12-slim

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Copy dependency files first (Docker layer caching)
COPY services/api/pyproject.toml services/api/uv.lock ./

# Sync dependencies using uv
RUN uv sync --frozen

# Copy the rest of the application code
COPY services/api/ ./
COPY services/reporting/ /app/reporting/
COPY data/ /app/data/
COPY docs/company-knowledge-base/ /app/docs/company-knowledge-base/

# Expose the port the API runs on
EXPOSE 8020

# Default command: start uvicorn with reload
CMD ["uv", "run", "uvicorn", "main:app", "--reload", "--port", "8020", "--host", "0.0.0.0"]