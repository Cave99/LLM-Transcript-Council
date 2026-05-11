# Frontend

React + TypeScript + Vite frontend for the graph-native evaluation workbench.

## Conventions

- API calls live in `src/api/client.ts`; shared response types live in `src/api/types.ts`.
- Tailwind tokens in `src/styles/globals.css` mirror the original FastHTML UI colors.
- shadcn-style primitives live in `src/components/ui/` and stay compact, calm, and workbench-oriented.
- React Flow nodes map directly to backend `GraphNode` rows: `x/y` are positions, `width/height` are persisted geometry, and sockets become handles.

Run from repo root:

```bash
pnpm dev
```
