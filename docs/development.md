# Development

## Prerequisites

Python 3.12+, Node.js 22+ and Docker Compose v2 for production-equivalent tests. `uv` is optional. Never use real exports in test fixtures, commits, logs or screenshots.

```sh
python3.12 -m venv .venv
source .venv/bin/activate
pip install --require-hashes -r infrastructure/docker/api-requirements.lock
pip install --no-deps -e apps/api
pytest apps/api/tests tests/security tests/integration -q
```

```sh
cd apps/web
npm ci
npm run dev
npm run build
npm test -- --run
npx playwright install chromium
npx playwright test
```

The Vite development server proxies `/api` to the local backend. To start a local backend for synthetic testing, use a disposable SQLite database, explicitly disable secure cookies for local HTTP and set a random bootstrap secret:

```sh
export FINSIGHT_DATABASE_URL="sqlite:///$PWD/data/development.db"
export FINSIGHT_COOKIE_SECURE=false
export FINSIGHT_BOOTSTRAP_SECRET="$(openssl rand -hex 32)"
mkdir -p data
cd apps/api
alembic upgrade head
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Use an absolute SQLite database path when changing working directories. Production uses PostgreSQL. SQLite tests do not prove PostgreSQL locking, multi-worker safety or monetary storage equivalence.

## Validation layers

1. Unit tests: Decimal finance, source mapping, split/transfer semantics, malicious uploads and budgets.
2. API integration: owner setup, sessions, CSRF, imports, ownership and reversible corrections.
3. Frontend unit/browser tests: localized states, navigation, imports and synthetic mocked API flows.
4. Compose smoke: `python scripts/compose_smoke.py` on an **isolated synthetic installation only**.
5. Recovery: backup, restore and `python scripts/compose_smoke.py --verify-only`.
6. Publication: `python scripts/privacy_check.py --reviewed-images docs/screenshots/reviewed.json`, independent secret scanning, `pip-audit`, `npm audit` and full history review. Any replacement screenshot requires a new manual synthetic-data review and exact-hash approval.

CI includes these checks; confirm the actual run status rather than assuming a workflow definition means success. Do not log Compose environment configuration with secrets expanded.

## Contracts and ownership

See `docs/api-contract.md`. Money travels as decimal strings; converting it for a chart is presentation-only. No financial result may be calculated using JavaScript floating point and then persisted as truth. Mutations include `X-CSRF-Token`; the session cookie is HttpOnly. Services must apply owner scoping before fetching related entities.

Adding a database entity requires an Alembic migration and indexes/constraints, not merely a frontend type. Test optional integrations with fake providers; tests must not incur model charges or publish notifications.

When updating API dependencies, regenerate the universal deployment lock and review the diff:

```sh
uv pip compile apps/api/pyproject.toml --python-version 3.12 --universal --generate-hashes --output-file infrastructure/docker/api-requirements.lock
```
