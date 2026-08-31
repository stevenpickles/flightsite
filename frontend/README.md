# FlightSite Frontend

Vite + React 18 + TypeScript (strict) frontend for FlightSite. See
[`../docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md) (§5) and
[`../docs/DEVELOPMENT.md`](../docs/DEVELOPMENT.md) for project-wide context.

## Stack

Tailwind CSS + shadcn/ui + lucide-react, react-router-dom, Zustand (UI state),
TanStack Query (server state). ESLint + Prettier + tsc + Vitest + React
Testing Library for quality gates.

## Scripts

```bash
npm install

npm run dev             # start the Vite dev server
npm run build            # typecheck + production build
npm run preview          # preview the production build

npm run lint              # eslint
npm run format:check      # prettier --check
npm run typecheck         # tsc --noEmit (project references)
npm run test               # vitest run
npm run test:coverage       # vitest run --coverage (>= 70% gate)
```

## Layout

```text
src/
  components/shell/   App shell: sidebar, nav config, theme toggle
  components/ui/      shadcn/ui primitives
  pages/               Route-level placeholder pages (one per primary section)
  store/               Zustand stores (useUiStore: theme + sidebar state)
  lib/                 Small framework-agnostic helpers (theme, cn, query client)
  routes.tsx           Router configuration
```

Feature work (map, live data, settings, etc.) lands under `src/features/` in
later slices, per `docs/ARCHITECTURE.md` §5.
