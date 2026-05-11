import type { ReactNode } from "react";

export function EmptyState({ title, body, action }: { title: string; body: string; action?: ReactNode }) {
  return (
    <div className="grid justify-items-start gap-2 rounded-lg border border-dashed border-line-strong bg-surface p-5">
      <h3 className="text-sm font-bold">{title}</h3>
      <p className="max-w-prose text-sm text-muted">{body}</p>
      {action ? <div className="mt-1">{action}</div> : null}
    </div>
  );
}

