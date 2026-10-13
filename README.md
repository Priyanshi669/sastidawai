# Sasti Dawai Frontend

Mobile-first React/Vite/TypeScript frontend for the Sasti Dawai medicine-identification experience. The current build is intentionally in mock mode so the complete UX can be exercised before the FastAPI and ML services are available.

## Run locally

```bash
npm install
npm run dev
```

Open `http://localhost:5173/`. Validate with `npm run check` and create a production build with `npm run build`.

## Mock and API modes

Copy `.env.example` to `.env.local` for local configuration:

```bash
VITE_API_BASE_URL=http://localhost:8000
VITE_USE_MOCKS=true
```

With `VITE_USE_MOCKS=true`, scanning, search, alternatives, and Kendra flows use clearly labelled sample data. Set it to `false` only when the FastAPI contract is available. The typed adapters live under `src/services/api/`; UI components do not calculate medical equivalence or verified savings.

## Main routes

- `/home` - scan-first home experience
- `/scan` - camera/upload fallback and explicit demo scan
- `/scan/review` and `/results` - editable extraction review and safety-labelled result
- `/search`, `/saved`, `/kendras`, `/history`, `/settings` - supporting product flows

The app stores only language, explicit demo saved items, and demo history in local storage. It does not persist raw images.
