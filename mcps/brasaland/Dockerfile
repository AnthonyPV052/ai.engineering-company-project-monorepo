FROM python:3.12-slim

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Copy dependency files first (Docker layer caching)
COPY mcps/brasaland/pyproject.toml mcps/brasaland/uv.lock ./

# Sync dependencies using uv
RUN uv sync --frozen

# Copy the rest of the application code
COPY mcps/brasaland/brasaland/ ./brasaland/

# Expose the port the MCP server runs on
EXPOSE 8100

# Default command: start the MCP server
CMD ["uv", "run", "python", "-m", "brasaland.server"]