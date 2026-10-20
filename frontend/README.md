# Frontend

Vite + React 19 + TypeScript + Tailwind v4. Types are generated from `openapi.json` (`pnpm gen:types`).

```bash
pnpm i
cp .env.example .env   # VITE_API_BASE_URL=http://localhost:7860
pnpm dev
```

| Script | |
| --- | --- |
| `pnpm dev` | Vite on :5173, proxies `/api` `/health` `/ready` |
| `pnpm gen:types` | `openapi-typescript` → `src/types/api.ts` |
| `pnpm test` | Vitest (jsdom) |
| `pnpm build` | `tsc -b` + Vite |
| `pnpm e2e` | Playwright smoke (recorded session, no live API) |

Vercel: set root directory to `frontend`, env `VITE_API_BASE_URL` to the Space origin. Recorded sessions live in `public/recorded/` and load without the API.
