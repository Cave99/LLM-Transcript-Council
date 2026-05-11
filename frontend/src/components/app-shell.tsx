import { Link, NavLink, Outlet } from "react-router-dom";

export function AppShell() {
  return (
    <>
      <header className="sticky top-0 z-40 flex h-[58px] items-center justify-between border-b border-line bg-bg/95 px-7 backdrop-blur">
        <Link to="/" className="inline-flex items-center gap-2.5 text-sm font-extrabold text-ink">
          <span className="h-2.5 w-2.5 rounded-[3px] bg-accent shadow-inner" />
          LLM-Transcript-Council
        </Link>
        <nav className="flex items-center gap-1 text-sm text-ink-soft">
          <NavLink className="rounded-md px-3 py-2 hover:bg-surface-muted hover:text-ink" to="/">
            Projects
          </NavLink>
          <NavLink className="rounded-md px-3 py-2 hover:bg-surface-muted hover:text-ink" to="/graphs/new">
            New Graph
          </NavLink>
        </nav>
      </header>
      <main className="mx-auto w-[min(1160px,calc(100vw-40px))] py-8 pb-20">
        <Outlet />
      </main>
    </>
  );
}
