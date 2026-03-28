# ══════════════════════════════════════════════════════════════════
#  Pyra — developer shortcuts
# ══════════════════════════════════════════════════════════════════

BACKEND_DIR := backend
FRONTEND_DIR := frontend

.PHONY: help migrate migrate-new migrate-down migrate-history \
        test test-cov seed dev-backend dev-frontend dev

help:
	@echo ""
	@echo "  DB migrations"
	@echo "    make migrate            — apply all pending migrations (alembic upgrade head)"
	@echo "    make migrate-new m=msg  — generate a new migration  (alembic revision --autogenerate -m msg)"
	@echo "    make migrate-down       — downgrade one step         (alembic downgrade -1)"
	@echo "    make migrate-history    — show migration history"
	@echo ""
	@echo "  Tests"
	@echo "    make test               — run all pytest tests"
	@echo "    make test-cov           — run tests with coverage report"
	@echo ""
	@echo "  Dev"
	@echo "    make seed               — seed the database with CAL FIRE data"
	@echo "    make dev-backend        — start FastAPI dev server"
	@echo "    make dev-frontend       — start Vite dev server"
	@echo "    make dev                — start both (requires tmux or two terminals)"
	@echo ""

# ── Migrations ────────────────────────────────────────────────────
migrate:
	cd $(BACKEND_DIR) && alembic upgrade head

migrate-new:
	@if [ -z "$(m)" ]; then echo "Usage: make migrate-new m=\"your message\""; exit 1; fi
	cd $(BACKEND_DIR) && alembic revision --autogenerate -m "$(m)"

migrate-down:
	cd $(BACKEND_DIR) && alembic downgrade -1

migrate-history:
	cd $(BACKEND_DIR) && alembic history --verbose

# ── Tests ─────────────────────────────────────────────────────────
test:
	cd $(BACKEND_DIR) && python -m pytest tests/ -v

test-cov:
	cd $(BACKEND_DIR) && python -m pytest tests/ -v --cov=app --cov-report=term-missing

# ── Dev ───────────────────────────────────────────────────────────
seed:
	cd database/seeds && python seed.py

dev-backend:
	cd $(BACKEND_DIR) && uvicorn app.main:app --reload --port 8000

dev-frontend:
	cd $(FRONTEND_DIR) && npm run dev

dev:
	@echo "Starting backend and frontend in parallel..."
	@make -j2 dev-backend dev-frontend