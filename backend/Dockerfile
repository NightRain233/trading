FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Enable bytecode compilation
ENV UV_COMPILE_BYTECODE=1
# Copy only the files needed for installation to optimize cache
COPY pyproject.toml uv.lock ./
# Install dependencies using uv sync --frozen (no dev dependencies)
RUN uv sync --frozen --no-install-project --no-dev

COPY . .

# Create data directory
RUN mkdir -p data

# Use the environment created by uv
CMD ["uv", "run", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
