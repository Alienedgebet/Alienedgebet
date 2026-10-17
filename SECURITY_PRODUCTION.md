# AlienEdge production security runbook

## Required Vercel configuration

- Set the Vercel Root Directory to `alienedge-frontend`.
- Set the server-only variable `BACKEND_API_URL=https://api.alienedge.tech` for Production.
- Do not set `BACKEND_API_URL` with a `NEXT_PUBLIC_` prefix.
- Do not use `NEXT_PUBLIC_API_URL` in Production; the browser uses the same-origin `/api` proxy.
- Configure Vercel Deployment Protection for Preview deployments.
- Do not attach production-only variables or SportMonks credentials to Preview deployments.

## Backend configuration

- The API service must remain bound to `127.0.0.1:8000`.
- Set `CORS_ALLOWED_ORIGINS=https://www.alienedge.tech` in the backend environment.
- Set `APP_ENV=production`.
- Set a strong `ADMIN_TOKEN` in the protected backend environment.
- Set `AUTH_DB_PATH` to a private writable path owned by the `alienedge` service account.
- Keep the SportMonks key only in the backend environment; never add it to Vercel variables.

## Mandatory secret response

The previously exposed SportMonks credential is compromised. Revoke it, create a replacement, and review provider usage before launch. Removing source fallbacks does not make the old key safe.

## Verification before launch

1. Logged-out product API request returns 401.
2. Unauthenticated browser route redirects to `/login`.
3. User A cannot read, patch, or delete User B's alert rules.
4. Unrelated CORS origins receive no `Access-Control-Allow-Origin` header.
5. The client JavaScript contains no SportMonks key or private backend secret.
6. Direct public access to port 8000 fails.
7. `/docs`, `/openapi.json`, and `/redoc` are not publicly available in production.
8. Existing engine/API tests and the frontend production build pass.
