.PHONY: help install dev dev-fe dev-be build build-fe docker-up docker-down docker-build docker-build-x docker-save docker-logs clean deploy deploy-up deploy-images deploy-full deploy-images-tx deploy-full-tx


# 初始化项目: make install

# 启动全栈：make dev（同时启动前后端，方便本地快速调试）
# 只启前端：make dev-fe
# 只启后端：make dev-be

# Docker 容器管理
# 构建镜像：make docker-build（本地架构）
# 交叉编译（linux/amd64）：make docker-build-x
# 导出镜像 tar.gz：make docker-save
# 启动服务：make docker-up（后台运行）
# 停止服务：make docker-down
# 查看日志：make docker-logs
# 重启服务：make docker-restart

# 部署到远程服务器（无服务器端构建）
# 完整部署（构建+同步+上传镜像+启动）：make deploy-full
# 仅上传镜像+重启（镜像已构建时）：make deploy-images
# 同步代码：make deploy

# Default shell
SHELL := /bin/bash

# --- Local deploy config (gitignored) ---
# Copy Makefile.local.example to Makefile.local and fill in your server details.
-include Makefile.local

# Fallback defaults (empty = skip deploy targets that need a host)
DEPLOY_HOST ?=
DEPLOY_PATH ?=
DEPLOY_HOST_TX ?=
DEPLOY_PATH_TX ?=

help: ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

install: ## Install dependencies for both frontend and backend
	@echo "Installing frontend dependencies..."
	cd frontend && pnpm install
	@echo "Installing backend dependencies..."
	cd backend && uv sync

# --- Local Development ---

dev-fe: ## Run frontend in development mode
	cd frontend && pnpm dev

dev-be: ## Run backend in development mode
	cd backend && uv run uvicorn main:app --reload --host 127.0.0.1 --port 8000

dev: ## Run both frontend and backend locally (requires parallel execution)
	@echo "Starting frontend and backend..."
	@make -j 2 dev-fe dev-be

# --- Build ---

build-fe: ## Build frontend production bundle
	cd frontend && pnpm build

build: build-fe ## Build all (frontend only for now, backend is interpreted)

# --- Docker Management ---

docker-build: ## Build docker images using docker compose
	docker compose build

docker-build-x: ## Build linux/amd64 images locally (for cross-platform deploy to x86 servers)
	@echo "Building backend image for linux/amd64..."
	docker buildx build --platform linux/amd64 -t trading-backend:latest ./backend --load
	@echo "Building frontend image for linux/amd64..."
	docker buildx build --platform linux/amd64 -t trading-frontend:latest ./frontend --load

docker-save: ## Export images to /tmp/trading-images.tar.gz
	docker save trading-backend:latest trading-frontend:latest | gzip > /tmp/trading-images.tar.gz
	@ls -lh /tmp/trading-images.tar.gz

up: ## Start docker containers in background
	docker compose up -d

down: ## Stop and remove docker containers
	docker compose down

logs: ## View docker container logs
	docker compose logs -f

restart: down up ## Restart docker containers

# --- Deployment ---

_check_host: ## Guard: fail if DEPLOY_HOST is not set
	@test -n "$(DEPLOY_HOST)" || (echo "ERROR: DEPLOY_HOST not set. Run: cp Makefile.local.example Makefile.local && edit it." >&2 && exit 1)

deploy: _check_host ## Sync project to remote server using rsync
	rsync -avz --filter=':- .gitignore' --exclude='.git' ./ $(DEPLOY_HOST):$(DEPLOY_PATH) 

deploy-up: deploy ## Deploy and start docker containers on remote
	ssh $(DEPLOY_HOST) "cd $(DEPLOY_PATH) && docker compose up -d --build"

deploy-tx: ## Sync project to remote server using rsync
	rsync -avz --filter=':- .gitignore' --exclude='.git' ./ $(DEPLOY_HOST_TX):$(DEPLOY_PATH_TX) 

deploy-up-tx: deploy-tx ## Deploy and start docker containers on remote
	ssh $(DEPLOY_HOST_TX) "cd $(DEPLOY_PATH_TX) && docker compose up -d --build"

deploy-images: docker-save ## Upload pre-built images and restart on remote (no server-side build)
	scp /tmp/trading-images.tar.gz $(DEPLOY_HOST):$(DEPLOY_PATH)/
	ssh $(DEPLOY_HOST) "cd $(DEPLOY_PATH) && docker load < trading-images.tar.gz && printf 'services:\n  backend:\n    image: trading-backend:latest\n    build: ~\n  frontend:\n    image: trading-frontend:latest\n    build: ~\n' > docker-compose.override.yml && docker compose down && docker compose up -d && docker compose ps"

deploy-full: docker-build-x deploy deploy-images ## Full deploy: cross-build images, sync code, upload and restart
	@echo "Full deploy complete."

deploy-images-tx: docker-save ## Upload pre-built images and restart on TX remote (no server-side build)
	scp /tmp/trading-images.tar.gz $(DEPLOY_HOST_TX):$(DEPLOY_PATH_TX)/
	ssh $(DEPLOY_HOST_TX) "cd $(DEPLOY_PATH_TX) && docker load < trading-images.tar.gz && printf 'services:\n  backend:\n    image: trading-backend:latest\n    build: ~\n  frontend:\n    image: trading-frontend:latest\n    build: ~\n' > docker-compose.override.yml && docker compose down && docker compose up -d && docker compose ps"

deploy-full-tx: docker-build-x deploy-tx deploy-images-tx ## Full deploy to TX: cross-build images, sync code, upload and restart
	@echo "Full deploy to TX complete."

# --- Cleanup ---

clean: ## Clean up build artifacts and cache
	@echo "Cleaning frontend..."
	rm -rf frontend/dist frontend/node_modules
	@echo "Cleaning backend..."
	rm -rf backend/.venv backend/__pycache__ backend/.pytest_cache
	@echo "Done."
