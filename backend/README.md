# Backend

FastAPI bootstrap for AGRO Logistics MVP.

## Local Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --reload --app-dir backend
```

Health check:

```bash
curl http://127.0.0.1:8000/health
```

Run tests:

```bash
pytest
```

## Scope

This bootstrap only includes app wiring, settings, logging, a health endpoint, and test structure.

Out of scope for this step:

- Domain models
- KAPSO integration
- Business endpoints
- AI layer
- Database migrations

