FROM python:3.12.13-slim@sha256:229a2c5bfa27522db7815ea81f9bed70af17ccb9de9fc7ad142b1877b5830d36
COPY --from=ghcr.io/astral-sh/uv:0.12.3@sha256:2d890623d310b57771ce840f0da5eed5fc6d657da05ffaa45d82797b53fa3abc /uv /uvx /bin/

ARG HTTP_PROXY
ARG HTTPS_PROXY
# Proxy only used during build (ARG), NOT baked into runtime ENV
# to avoid SSL issues with data fetching (curl-cffi + proxy = TLS errors)

WORKDIR /app

# Use Tsinghua PyPI mirror (for servers without direct PyPI access)
ENV UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

# Enable bytecode compilation
ENV UV_COMPILE_BYTECODE=1
# Copy only the files needed for installation to optimize cache
COPY pyproject.toml uv.lock ./
# Install dependencies (without --frozen: lockfile pins files.pythonhosted.org URLs unreachable from China servers)
RUN --mount=type=cache,id=trading-uv-cache,target=/root/.cache/uv,sharing=locked \
    uv sync --no-install-project --no-dev

COPY . .

# Create data directory
RUN mkdir -p data

# Use the environment created by uv
CMD ["uv", "run", "--no-dev", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
