.PHONY: help install dev dev-fe dev-be build build-fe docker-up docker-down docker-build docker-logs clean deploy


# 初始化项目: make install

# 启动全栈：make dev（同时启动前后端，方便本地快速调试）
# 只启前端：make dev-fe
# 只启后端：make dev-be

# Docker 容器管理
# 构建镜像：make docker-build
# 启动服务：make docker-up（后台运行）
# 停止服务：make docker-down
# 查看日志：make docker-logs
# 重启服务：make docker-restart

# Default shell
SHELL := /bin/bash

# Deployment config (Update these)
DEPLOY_HOST := root@8.153.71.148
DEPLOY_PATH := /home/zsd/trading

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
	cd backend && uv run uvicorn main:app --reload --host 0.0.0.0 --port 8000

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

up: ## Start docker containers in background
	docker compose up -d

down: ## Stop and remove docker containers
	docker compose down

logs: ## View docker container logs
	docker compose logs -f

restart: down up ## Restart docker containers

# --- Deployment ---

deploy: ## Sync project to remote server using rsync
	rsync -avz --filter=':- .gitignore' --exclude='.git' ./ $(DEPLOY_HOST):$(DEPLOY_PATH) --delete

# --- Cleanup ---

clean: ## Clean up build artifacts and cache
	@echo "Cleaning frontend..."
	rm -rf frontend/dist frontend/node_modules
	@echo "Cleaning backend..."
	rm -rf backend/.venv backend/__pycache__ backend/.pytest_cache
	@echo "Done."
