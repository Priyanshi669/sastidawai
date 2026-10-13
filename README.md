# Sasti Dawai

**Sasti Dawai** (सस्ती दवाई) is a mobile-first PWA that helps users identify medicines by scanning barcodes or uploading photos, find affordable alternatives, and locate nearby Jan Aushadhi Kendras on a map.

Built with React, TypeScript, Vite, and Leaflet. Currently runs in mock mode — no live backend required to explore the full UX.

---

## Quick Start

```bash
npm install
npm run dev
```

Open `http://localhost:5173/`.

**Production build:**
```bash
npm run build
npm run preview
```

**Validate:**
```bash
npm run check
```

---

## Configuration

Copy `.env.example` to `.env.local`:

```env
VITE_API_BASE_URL=http://localhost:8000
VITE_USE_MOCKS=true
```

| Variable | Default | Purpose |
|---|---|---|
| `VITE_USE_MOCKS` | `true` | Uses mock data when `true`. Set to `false` when the FastAPI backend is available. |
| `VITE_API_BASE_URL` | — | Base URL for the real backend API. |

---

## Tech Stack — Full Breakdown

### Core Framework

| Technology | Version | Why It's Used |
|---|---|---|
| **React** | 19.x | Component-based UI with hooks for state management. Latest version with improved concurrent rendering. |
| **TypeScript** | 5.x | Type safety across the entire codebase — catches bugs at compile time, better IDE support, self-documenting code. |
| **Vite** | 6.x | Lightning-fast dev server with instant HMR (Hot Module Replacement). Optimized production builds with Rollup. |

### Routing & Navigation

| Technology | Why It's Used |
|---|---|
| **React Router DOM** | Client-side routing for a SPA experience. Supports nested routes, route guards, and programmatic navigation. Enables smooth page transitions with `AnimatePresence`. |

### Animations

| Technology | Why It's Used |
|---|---|
| **Framer Motion** | Production-ready animation library. Used for smooth page transitions (slide-in/slide-out), micro-interactions, and the loading screen. Supports `AnimatePresence` for exit animations. |

### Mapping

| Technology | Why It's Used |
|---|---|
| **Leaflet** | Open-source interactive map library. Lightweight, mobile-friendly, and works with OpenStreetMap tiles. Used for the Kendras page to show Jan Aushadhi locations. |
| **OpenStreetMap** | Free, open-source map tiles. No API key required. Used as the tile layer for Leaflet. |

### Internationalization (i18n)

| Technology | Why It's Used |
|---|---|
| **i18next** | Full-featured i18n framework. Supports interpolation, pluralization, lazy loading, and language detection. |
| **react-i18next** | React bindings for i18next. Provides `useTranslation` hook for easy access to translations in components. |

**Supported Languages:**
- English (`en`)
- Hindi (`hi`)
- Marathi (`mr`)
- Gujarati (`gu`)
- Tamil (`ta`)

### State Management

| Technology | Why It's Used |
|---|---|
| **React Context API** | Lightweight global state for language, saved medicines, scan history, and theme. No external state library needed for this app's complexity. |
| **useMemo / useCallback** | Performance optimizations to prevent unnecessary re-renders. |

### Styling

| Technology | Why It's Used |
|---|---|
| **CSS Custom Properties** | Design tokens (colors, spacing, radii, shadows) defined as CSS variables. Enables instant theme switching (light/dark mode). |
| **Vanilla CSS** | No CSS framework — full control over every pixel. Smaller bundle size, no unused styles. |
| **Glassmorphism** | Modern frosted-glass effect using `backdrop-filter: blur()` with semi-transparent backgrounds. |
| **CSS Grid & Flexbox** | Modern layout techniques for responsive design. |

### PWA (Progressive Web App)

| Technology | Why It's Used |
|---|---|
| **Web App Manifest** | Enables "Add to Home Screen" on mobile devices. Defines app name, icons, theme colors, and display mode. |
| **Service Worker** | (Future) Will enable offline functionality and asset caching. |

### Camera & Media

| Technology | Why It's Used |
|---|---|
| **getUserMedia API** | Native browser API for accessing device camera. Used for real-time medicine strip scanning. |
| **Canvas API** | Image quality analysis (brightness, blur detection) by drawing images to canvas and analyzing pixel data. |

### Data Persistence

| Technology | Why It's Used |
|---|---|
| **localStorage** | Stores user preferences (language, theme), saved medicines, and scan history. All data stays on the user's device — no server storage. |

### Build & Development Tools

| Technology | Why It's Used |
|---|---|
| **npm** | Package management and script running. |
| **ESLint** | Code quality and consistency. |
| **Prettier** | Automatic code formatting. |
| **TSConfig** | TypeScript configuration with strict mode enabled. |

---

## Architecture Overview

### Component Architecture

```
App (Router + AnimatePresence)
├── AppShell (Sidebar + Topbar layout)
│   ├── Sidebar (Navigation)
│   ├── Topbar (Search bar)
│   └── Page Content (Routes)
│       ├── HomePage
│       ├── ScannerPage
│       ├── SearchPage
│       ├── ResultPage
│       ├── KendrasPage (Leaflet Map)
│       ├── SettingsPage
│       ├── SavedPage
│       ├── HistoryPage
│       └── ...
└── Camera Modal (Overlay)
```

### Data Flow

```
User Action → Component → AppProvider (Context) → localStorage
                              ↓
                        API Layer (mock/real)
                              ↓
                        Response → Component Re-render
```

### API Layer

The app uses a **dual-mode API layer**:

- **Mock API** (`mockApi.ts`) — Returns hardcoded sample data. Used when `VITE_USE_MOCKS=true`.
- **Real API** (`realApi.ts`) — Makes HTTP requests to the FastAPI backend. Used when `VITE_USE_MOCKS=false`.

Both implement the same `MedicineApi` interface, so switching between modes requires only an environment variable change.

---

## Features

- **Medicine Scanning** — Camera or upload a photo of a medicine strip
- **Search** — Find medicines by brand, generic name, or ingredient
- **Alternatives** — Compare prices and find cheaper substitutes
- **Kendras** — Interactive Leaflet map showing nearby Jan Aushadhi Kendras with Google Maps directions
- **Saved Medicines** — Personal reference list (stored locally)
- **Scan History** — Recent scans with re-scan option
- **Multi-language** — 5 languages with full UI translation
- **Dark Mode** — Toggle between light and dark themes
- **Responsive** — Mobile-first, works on all screen sizes
- **Smooth Transitions** — Framer Motion page transitions
- **Image Quality Check** — Rejects blurry or too-dark photos
- **PWA** — Installable on mobile devices

---

## Project Structure

```
src/
├── app/              # Global state (AppProvider context)
├── components/       # Shared components
│   ├── common/       # SearchBar, MedicineCard, EmptyState, etc.
│   ├── layout/       # AppShell (sidebar + topbar)
│   └── medicine/     # MedicineCard, PriceComparison
├── features/         # Route-level pages
│   ├── home/         # Scan-first home with camera modal
│   ├── scan/         # Camera/upload with quality checks
│   ├── search/       # Medicine search with filters
│   ├── results/      # Safety-labelled result with match status
│   ├── kendras/      # Leaflet map + Google Maps directions
│   ├── settings/     # Language, dark mode, privacy, clear data
│   ├── saved/        # Saved medicines list
│   ├── history/      # Scan history
│   └── onboarding/   # Language selection intro
├── i18n/             # Translations (en, hi, mr, gu, ta)
├── lib/              # Mock data
├── services/         # API layer (mock + real adapters)
│   └── api/          # contracts.ts, mockApi.ts, realApi.ts, index.ts
├── styles/           # Design tokens + global styles
│   ├── tokens.css    # CSS custom properties (colors, spacing, radii)
│   └── global.css    # All component styles
└── types/            # TypeScript type definitions
```

---

## Routes

| Path | Description |
|---|---|
| `/home` | Scan-first home with camera modal, quick links, recent scans |
| `/scan` | Camera/upload with image quality checks |
| `/scan/processing` | Animated processing loader |
| `/scan/review` | Editable extraction review form |
| `/results` | Safety-labelled result with match status |
| `/alternatives` | Alternative medicines comparison |
| `/search` | Search with filters, debounced |
| `/saved` | Saved medicines list |
| `/kendras` | Leaflet map with Jan Aushadhi Kendra locations |
| `/history` | Scan history list |
| `/settings` | Language, dark mode, privacy, clear data |
| `/onboarding` | Language selection + intro |

---

## Data & Privacy

- All user data (saved medicines, history, preferences) is stored **only in localStorage** on the user's device
- **No raw images are persisted** — photos are processed in-memory only
- **No account required** — the app works fully offline in mock mode
- The mandatory disclaimer **"Confirm with your doctor or pharmacist"** is displayed throughout the app

---

## Scripts

| Command | Description |
|---|---|
| `npm run dev` | Start Vite dev server (port 5173) |
| `npm run build` | Production build to `dist/` |
| `npm run preview` | Preview production build |
| `npm run check` | TypeScript check + lint |
| `npm run test` | Run test suite |

---

## Testing on Mobile

Use **localtunnel** for HTTPS (required for camera API):

```bash
npx localtunnel --port 5173
```

Then open the generated `https://xxx.loca.lt` URL on your phone.

---

## License

MIT
