# Frontend

React + TypeScript + Vite frontend for the graph-native evaluation workbench.

## Conventions

- API calls live in `src/api/client.ts`; shared response types live in `src/api/types.ts`.
- Tailwind tokens in `src/styles/globals.css` define the local workbench palette.
- shadcn-style primitives live in `src/components/ui/` and stay compact, calm, and workbench-oriented.
- React Flow nodes are generated from the graph spec; persisted layout stores semantic node positions by spec id.

Run from repo root:

```bash
pnpm dev
```
