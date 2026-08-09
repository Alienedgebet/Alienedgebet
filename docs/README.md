# AlienEdge Documentation

Long-form reference lives here. Agent rules stay short in `.cursorrules`.

## Index

| Document | Purpose |
|----------|---------|
| [BLUEPRINT.md](./BLUEPRINT.md) | Architecture, engine map, frontend design, social spec, coding standards |
| [API.md](./API.md) | **Authoritative** REST contract — derived from `api/main.py` |
| [PHASES.md](./PHASES.md) | Phased frontend build order and agent workflow |

## Source-of-truth hierarchy

1. **`api/main.py`** — REST paths and query params (backend contract)
2. **`main.py`** — which engines run in the CLI pipeline
3. **`alienedge-frontend/lib/api.ts`** — typed frontend client (must match `api/main.py`)
4. **`docs/BLUEPRINT.md`** — product/architecture guidance (may lag code; API section defers to `API.md`)

## Assets (do not rewrite)

- `alienedge-frontend/tailwind.config.ts`
- `alienedge-frontend/app/globals.css`
- `alienedge-frontend/components/ui/*`
