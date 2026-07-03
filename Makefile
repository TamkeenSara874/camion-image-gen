.PHONY: install dev frontend test lint format batch extract-colors build run

install:
	pip install -r requirements.txt

dev:
	uvicorn main:app --reload --port 8010

frontend:
	streamlit run frontend/app.py

test:
	pytest tests/ -v --tb=short --cov=. --cov-report=term-missing --cov-report=html

lint:
	ruff check . && ruff format --check .

format:
	ruff format .

batch:
	python run_batch.py

extract-colors:
	python scripts/extract_brand_colors.py

build:
	docker build -t camion-image-gen:latest .

run:
	docker-compose up
