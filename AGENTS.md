# Repository Guidelines

## Project Structure

This checkout currently contains product specifications only, under `docs/`:
`Sasti-Dawai-PRD.pdf` is the parent PRD; the backend, frontend, and ML PDFs define their respective implementation plans. No source, test, or Git metadata is present yet. When implementation begins, follow the planned layout: `apps/web/` for the React/Vite PWA, `apps/api/` for FastAPI, `data/` for raw inputs, ETL, and evaluation fixtures, and `.github/workflows/` for CI. Keep `docs/decisions.md` and API/evaluation documentation updated.

## Build, Test, and Development Commands

There are no runnable commands in the current documentation-only checkout. Once the planned apps exist, document and verify commands such as:

- `npm run dev` / `npm run build` in `apps/web` for local PWA development and production builds.
- `pytest` in `apps/api` for unit, API, integration, and safety tests.
- `uvicorn app.main:app --reload` in `apps/api` for the local API.
- `python data/eval/eval.py` for the golden-set evaluation.

Add a root README with exact setup, migration, seed, and deployment commands before relying on them.

## Coding Style & Naming

Use TypeScript with existing project formatting/lint rules for the frontend; prefer `PascalCase` React components, `camelCase` functions, and feature-oriented folders. Use Python 3.11+, type hints, Pydantic schemas, thin FastAPI routes, service/repository separation, and `snake_case` modules. Keep prompts and schemas versioned. Do not add competing styling or fuzzy-matching systems without a measured reason.

## Testing Guidelines

Use Vitest/React Testing Library for UI behavior and pytest/HTTPX for backend contracts. Cover unit normalization, combinations, release/form/route matching, savings arithmetic, malformed provider output, failures, and the rule that fuzzy/vector similarity can never produce `EXACT`. Run the golden evaluation on meaningful model or threshold changes; any false `EXACT` result blocks release. Test camera and responsive flows on real Android and iOS devices when available.

## Safety, Security & Configuration

Deterministic, verified data - not an LLM - must decide equivalence, prices, savings, and stock claims. Fail closed on uncertainty. Keep secrets in environment variables and commit only `.env.example`; never log raw photos or unnecessary personal data. Preserve the mandatory "Confirm with your doctor or pharmacist" disclaimer.

## Commits & Pull Requests

No Git history is available, so use Conventional Commits (for example, `feat(api): add scan confirmation`). PRs should explain scope, link an issue or decision when applicable, include tests and known limitations, and attach screenshots or device notes for UI changes. Report actual test/evaluation results; do not claim unverified deployments or metrics.
