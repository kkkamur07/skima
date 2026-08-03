---
name: fastapi-best-practices
description: Concise FastAPI best practices for layered architecture, DTO contracts, clean routers, and practical testing.
---

# FastAPI Best Practices (Layered + DDD)

High-signal conventions for building clean, scalable APIs with FastAPI + Pydantic.

## Recommended structure

```txt
backend/
  main.py
  core/
    settings.py              # BaseSettings + model_validator + computed_field
  api/
    main.py                  # app + middleware + include_router
    deps.py                  # settings/session/auth dependencies
    routers/
      health.py
      jobs.py
      companies.py
      seekers.py
  jobs/
    domain/
      job.py                 # entities + enums
    api_schemas/
      ...
    infrastructure/
      __init__.py            # repositories/adapters
    services/
      __init__.py            # use-cases
tests/
```

## Core rules

- Keep layers explicit: router -> service -> repository.
- Keep settings in `core/settings.py` via `BaseSettings`.
- Use `@model_validator` + `@computed_field` for config validation/derivations.
- Keep routers thin; put business logic in services.
- Raise `HTTPException` with consistent payloads.
- Use Sentry for production error monitoring.
- Generate frontend types from OpenAPI with `openapi-ts`.

## DTO pattern (important)

DTO guidance for user-style resources:
- `UserCreate`: create payload from client.
- `UserUpdate`: patch/update input payload.
- `UserModify`: middle-state DTO after service/domain transforms.
- `UserPublic`: final external/public shape returned to clients.

```python
from fastapi import APIRouter, HTTPException

router = APIRouter()

@router.get("/", response_model=UsersPublic)
def list_users(session: SessionDep, current_user: CurrentUser, skip: int = 0, limit: int = 100):
    items = service.list_items(skip=skip, limit=limit)
    if items is None:
        raise HTTPException(status_code=404, detail="Users not found")
    return items

@router.post("/", response_model=UserModify)
def create_user(payload: UserCreate, session: SessionDep, current_user: CurrentUser):
    return service.create_user(payload, actor=current_user)

@router.put("/{user_id}", response_model=UserModify)
def update_user(user_id: str, payload: UserUpdate, session: SessionDep, current_user: CurrentUser):
    updated = service.update_user(user_id, payload, actor=current_user)
    if not updated:
        raise HTTPException(status_code=404, detail="User not found")
    return updated

@router.delete("/{user_id}")
def delete_user(user_id: str, session: SessionDep, current_user: CurrentUser):
    service.delete_user(user_id, actor=current_user)
    return {"message": "Deleted successfully"}
```

## Testing essentials

```python
def test_create_job_integration(client):
    payload = {"title": "Backend Engineer", "company_id": "abc"}
    resp = client.post("/jobs", json=payload)
    assert resp.status_code == 201
    body = resp.json()
    assert body["title"] == "Backend Engineer"
```

Running tests:
- `python -m pytest tests/integration`
- `uv run pytest tests/integration`

Must-add tests next:
- Negative-path tests (invalid payload/auth/not found)
- Contract tests for response shapes
- Pagination boundary tests
- Service-layer unit tests
