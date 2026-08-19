#!/usr/bin/env bash
set -u

project_dir="$(cd "$(dirname "$0")/.." && pwd)"
api_base="${PORTFOLIO_API_BASE:-http://127.0.0.1:8000/api}"
report_path="${PORTFOLIO_REPORT_PATH:-$project_dir/backend/backtest_results/openclaw_portfolio_daily.md}"
lock_file="$project_dir/backend/backtest_results/portfolio_daily_runner.lock"

mkdir -p "$(dirname "$report_path")"
exec 9>"$lock_file"
if ! flock -n 9; then
  echo "portfolio daily job is already running" >&2
  exit 75
fi

cd "$project_dir"
docker compose exec -T backend uv run --no-dev python portfolio_daily_job.py
job_status=$?

python3 scripts/openclaw_supertrend_alerts.py \
  --api-base "$api_base" \
  --mode daily-brief \
  --format markdown > "$report_path"
brief_status=$?

if [ "$job_status" -ne 0 ] || [ "$brief_status" -ne 0 ]; then
  echo "daily job status=$job_status, brief status=$brief_status" >&2
  exit 1
fi
