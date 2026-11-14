# FinSight web

Responsive private finance frontend. React 19, TypeScript, Vite, Tailwind, React Router, TanStack Query and Recharts. German by default, English switch and persistent light/dark preference. No demo financial values in the app.

```sh
npm ci
npm run dev
npm run build
npm test
npx playwright install chromium
npm run test:e2e
```

Vite defaults to port 5173 and proxies `/api` to `http://localhost:8000`. Local HTTP requires the API's explicit development cookie setting (`FINSIGHT_COOKIE_SECURE=false`). Use HTTPS and secure cookies in production.

```sh
docker build -t finsight-web .
docker run --rm --network YOUR_COMPOSE_NETWORK -p 8080:8080 finsight-web
```

The nginx upstream hostname must resolve to `api:8000`. Non-root UID 101, port 8080, SPA fallback, same-origin API, health endpoint `/healthz`, restrictive CSP and API access-log suppression are included. API paths are not rewritten. TLS belongs on the public reverse proxy. Container deployment has not been verified by frontend browser tests.

Nginx preserves the full public `Host` including non-default ports, and access logs are disabled for **all** locations. For upstream HTTPS termination, configure the API's exact canonical `FINSIGHT_ALLOWED_ORIGINS` and secure cookies, and restrict public Host/proxy trust at the ingress. See [API.md](API.md#public-origin--https-proxy-topology); do not disable origin validation or trust arbitrary client forwarding headers.

See [API.md](API.md) for exact schemas, security behavior, endpoint assumptions and limitations. Browser tests mock all API routes with synthetic data; they never open the private workbook. Generated browser traces/build output/node_modules are ignored and are not release source.

## Verification boundary

Local production build and unit/browser tests are executable with the commands above. Browser coverage includes desktop and mobile login/bootstrap, generic credential errors, CSRF propagation and rejection, currency separation, chart text alternatives, account edits, reversible classification, safe source rendering, preview-before-upload, bucket creation/atomic funding, contract evidence, optional AI defaults, nested ntfy configuration, keyboard drawer navigation and preference persistence. The desktop-only skip for the mobile drawer is intentional. These tests do not establish live API/deployment/third-party integration correctness.
