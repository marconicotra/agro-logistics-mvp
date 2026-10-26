# AGRO Backoffice

Backoffice web minimo para soporte/admin.

## Desarrollo local

Levantar backend:

```bash
.venv/bin/uvicorn app.main:app --app-dir backend --reload
```

Levantar frontend:

```bash
cd frontend
npm install
npm run dev
```

## Pruebas E2E

Prepará el entorno Python de la raíz como indica `backend/README.md`, después instalá dependencias y ejecutá Playwright:

```bash
cd frontend
npm ci
npm run test:e2e
npx playwright show-report playwright-report
```

El harness crea SQLite aislado, corre Chromium desktop/mobile y simula WhatsApp y extracción de carga. No usa el `.env` ni proveedores externos. Guía, límites y resultados de la primera auditoría: [`docs/27-guia-playwright.md`](../docs/27-guia-playwright.md) y [`docs/28-playwright-audit-2026-10-26.md`](../docs/28-playwright-audit-2026-10-26.md).

Variables opcionales:

```bash
VITE_API_BASE_URL=http://127.0.0.1:8000
VITE_OPERATOR_USER_ID=user_operator
VITE_OPERATOR_ROLE=operator
```

Los encabezados de operador solo sirven para desarrollo local. No configures
`INTERNAL_API_KEY` con prefijo `VITE_`: las variables `VITE_*` quedan incluidas
en el JavaScript enviado al navegador. En entornos compartidos, el cliente web
debe usar una sesion de operador verificada por el backend (integracion prevista
con Supabase Auth); el navegador no debe enviar la clave interna del servicio.
