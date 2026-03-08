# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Aperant (formerly Auto Claude) is an autonomous multi-agent coding framework that plans, builds, and validates software. It's a monorepo with a Python backend (CLI + agent logic) and an Electron/React frontend (desktop UI).

## Product Overview

Aperant is a desktop application (+ CLI) where users describe a goal and AI agents autonomously handle planning, implementation, and QA validation. All work happens in isolated git worktrees so the main branch stays safe.

**Core workflow:** User creates a task → Spec creation pipeline assesses complexity and writes a specification → Planner agent breaks it into subtasks → Coder agent implements (can spawn parallel subagents) → QA reviewer validates → QA fixer resolves issues → User reviews and merges.

## Critical Rules

**Claude Agent SDK only** — All AI interactions use `claude-agent-sdk`. Use `create_client()` from `core.client`, not `anthropic.Anthropic()` directly. It handles security hooks, tool permissions, and MCP server integration.

**i18n required** — All frontend user-facing text uses `react-i18next` translation keys. Add keys to both `en/*.json` and `fr/*.json`. Hardcoded strings in JSX/TSX break localization.

**Platform abstraction** — Use the platform modules in `apps/frontend/src/main/platform/` or `apps/backend/core/platform/` instead of `process.platform` directly. CI tests all three platforms.

**Python file encoding** — Always specify `encoding="utf-8"` for text file operations. Windows Python defaults to `cp1252`, causing errors with emoji and international characters.

**PR target** — Always target the `develop` branch for PRs, not `main`. Main is reserved for releases.

**No console.log in production** — Invisible in bundled Electron apps. Use Sentry for error tracking.

**No time estimates** — Provide priority-based ordering instead of duration predictions.

## Prerequisites

- **Python 3.12+** — Backend framework
- **Node.js 24+** / **npm 10+** — Electron frontend
- **CMake** — Required for building native dependencies (e.g., LadybugDB)
- **uv** (recommended) or **pip** — Python package manager

## Commands Quick Reference

### Setup
```bash
npm run install:all              # Install all dependencies (Python + Electron)
# Or separately:
cd apps/backend && uv venv && uv pip install -r requirements.txt
cd apps/frontend && npm install
```

### Running
```bash
npm run dev          # Development mode with HMR
npm run dev:debug    # Debug mode with verbose output
npm run dev:mcp      # Electron MCP server for AI debugging
npm start            # Production build + run

# CLI only
cd apps/backend && python run.py --spec 001
```

### Testing

| Stack | Run all | Run single test |
|-------|---------|-----------------|
| Backend | `cd apps/backend && .venv/bin/pytest tests/ -v` | `.venv/bin/pytest tests/test_foo.py::test_bar -v` |
| Frontend unit | `cd apps/frontend && npm test` | `cd apps/frontend && npx vitest run src/path/to/test.ts` |
| Frontend E2E | `cd apps/frontend && npm run test:e2e` | `cd apps/frontend && npx playwright test e2e/test-name.spec.ts` |
| Backend (root) | `npm run test:backend` | — |

**Backend pytest markers:** `@pytest.mark.slow` (skipped in CI by default), `@pytest.mark.integration` (external services), `@pytest.mark.smoke` (quick verification). Run slow tests: `pytest -m slow`.

**Backend testpaths:** `integrations/graphiti/tests`, `core/workspace/tests`. Uses `asyncio_mode = "strict"`.

### Code Quality
```bash
# Frontend
cd apps/frontend
npm run lint           # Biome check
npm run lint:fix       # Biome auto-fix
npm run typecheck      # TypeScript strict mode

# Backend
cd apps/backend && ruff check .
```

### Releases
```bash
node scripts/bump-version.js patch|minor|major  # Bump version
git push && gh pr create --base main             # PR to main triggers release
```

## Project Structure

```
Aperant/
├── apps/
│   ├── backend/                 # Python backend/CLI — ALL agent logic
│   │   ├── core/                # client.py, auth.py, worktree.py, platform/
│   │   ├── security/            # Command allowlisting, validators, hooks
│   │   ├── agents/              # planner, coder, session management
│   │   ├── qa/                  # reviewer, fixer, loop, criteria
│   │   ├── spec/                # Spec creation pipeline
│   │   ├── cli/                 # CLI commands (spec, build, workspace, QA)
│   │   ├── context/             # Task context building, semantic search
│   │   ├── runners/             # Standalone runners (spec, roadmap, insights, github)
│   │   ├── services/            # Background services, recovery orchestration
│   │   ├── integrations/        # graphiti/, linear, github
│   │   ├── merge/               # Intent-aware semantic merge for parallel agents
│   │   └── prompts/             # Agent system prompts (.md)
│   └── frontend/                # Electron desktop UI
│       └── src/
│           ├── main/            # Electron main process (agent/, terminal/, claude-profile/, ipc-handlers/, platform/)
│           ├── preload/         # Electron preload scripts (electronAPI bridge)
│           ├── renderer/        # React UI (components/, stores/, hooks/, contexts/)
│           ├── shared/          # Shared types, i18n, constants, utils
│           └── types/           # TypeScript type definitions
├── tests/                       # Backend test suite
└── scripts/                     # Build and utility scripts
```

## Architecture

### Backend

**Client:** `apps/backend/core/client.py` — `create_client()` returns a configured `ClaudeSDKClient`. Model and thinking level are user-configurable; use `phase_config.py` helpers to resolve values.

**Agent prompts** in `apps/backend/prompts/`: `planner.md`, `coder.md`/`coder_recovery.md`, `qa_reviewer.md`/`qa_fixer.md`, `spec_gatherer/researcher/writer/critic.md`, `complexity_assessor.md`.

**Spec directory:** Each spec in `.auto-claude/specs/XXX-name/` contains: `spec.md`, `requirements.json`, `context.json`, `implementation_plan.json`, `qa_report.md`, `QA_FIX_REQUEST.md`.

**Memory system:** Graph-based semantic memory (Graphiti) in `integrations/graphiti/`. Enable via Electron UI settings or `GRAPHITI_ENABLED=true` in `.env`.

### Frontend

**Tech stack:** React 19, TypeScript (strict), Electron 39, Zustand 5, Tailwind CSS v4, Radix UI, xterm.js 6, Vite 7, Vitest 4, Biome 2, Motion (Framer Motion)

**Path aliases** (tsconfig.json):

| Alias | Maps to |
|-------|---------|
| `@/*` | `src/renderer/*` |
| `@shared/*` | `src/shared/*` |
| `@preload/*` | `src/preload/*` |
| `@features/*` | `src/renderer/features/*` |
| `@components/*` | `src/renderer/shared/components/*` |
| `@hooks/*` | `src/renderer/shared/hooks/*` |
| `@lib/*` | `src/renderer/shared/lib/*` |

**Feature module structure** — features follow this layout:
```
features/[feature-name]/
├── components/        # Feature-specific React components
├── hooks/             # Feature-specific hooks
├── store/             # Zustand store
└── index.ts           # Public API exports
```

**State management:** All renderer state in `src/renderer/stores/` (Zustand). Key stores: `project-store.ts`, `task-store.ts`, `terminal-store.ts`, `settings-store.ts`, `github/issues-store.ts`, `github/pr-review-store.ts`. Main process also has stores: `src/main/project-store.ts`, `src/main/terminal-session-store.ts`.

**IPC pattern:** Renderer calls via `window.electronAPI.*`, main handles in `src/main/ipc-handlers/` (organized by domain). Preload scripts in `src/preload/` expose safe APIs.

**Styling:** Tailwind CSS v4, 7+ color themes in `src/shared/constants/themes.ts` (light/dark via CSS custom properties), `cn()` helper (`clsx` + `tailwind-merge`), CVA for component variants.

### Frontend Conventions

- **File naming:** PascalCase for components (`TaskCard.tsx`), camelCase with `use` for hooks (`useTaskStore.ts`), kebab-case for stores (`task-store.ts`)
- **TypeScript:** Prefer `type` over `interface`, use `export type` for type-only exports, no implicit `any`
- **Import order:** External libraries → Shared components/utilities → Feature imports → Types (with `import type`)

## i18n Guidelines

Translation files: `apps/frontend/src/shared/i18n/locales/{en,fr}/*.json`

**Namespaces:** `common`, `navigation`, `settings`, `dialogs`, `tasks`, `errors`, `onboarding`, `welcome`

```tsx
import { useTranslation } from 'react-i18next';
const { t } = useTranslation(['navigation', 'common']);

<span>{t('navigation:items.githubPRs')}</span>     // CORRECT
<span>GitHub PRs</span>                             // WRONG
```

When adding new UI text: add keys to ALL language files, use `namespace:section.key` format.

## Known Gotchas

**Electron path resolution** — Check path resolution differences between dev and production builds (`app.isPackaged`, `process.resourcesPath`). Paths that work in dev often break when bundled.

**Resetting PR Review State** — To clear all PR review data in `.auto-claude/github/`:
1. `rm .auto-claude/github/pr/logs_*.json` and `rm .auto-claude/github/pr/review_*.json`
2. Reset `pr/index.json` to `{"reviews": [], "last_updated": null}`
3. Reset `bot_detection_state.json` to `{"reviewed_commits": {}}` — the gatekeeper; without clearing it, already-seen commits are skipped

## E2E Testing (Electron MCP)

QA agents can interact with the running Electron app via Chrome DevTools Protocol:

1. Start app: `npm run dev:debug`
2. Set `ELECTRON_MCP_ENABLED=true` in `apps/backend/.env`
3. Run QA: `cd apps/backend && python run.py --spec 001 --qa`

Tools: `take_screenshot`, `click_by_text`, `fill_input`, `get_page_structure`, `send_keyboard_shortcut`, `eval`.

## Cross-Platform

Supports Windows, macOS, Linux. CI tests all three.

**Platform modules:** `apps/frontend/src/main/platform/` and `apps/backend/core/platform/`

Use `findExecutable()` and `joinPaths()` instead of hardcoded paths. Key functions: `isWindows()`, `isMacOS()`, `isLinux()`, `getPathDelimiter()`, `findExecutable(name)`, `requiresShell(command)`.
