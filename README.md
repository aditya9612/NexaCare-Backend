# Nexa-Care HMS Backend

Hospital Management System API built with FastAPI, SQLAlchemy, and PostgreSQL.

## Quick start

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env   # or edit .env
python run.py
```

API docs: http://localhost:8000/docs

## Docker

```bash
docker compose up --build
```

## Migrations

```bash
alembic upgrade head
```

## Tests

```bash
pytest app/tests -v
```
