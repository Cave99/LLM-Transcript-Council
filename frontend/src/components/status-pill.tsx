import type { StatusValue, GraphStatusValue } from "../api/types";
import { cn } from "../lib/utils";

export function StatusPill({ status }: { status: StatusValue | GraphStatusValue }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border px-2.5 py-1 text-xs font-bold",
        status === "complete" && "border-success/30 bg-success-soft text-success",
        status === "running" && "border-warning/30 bg-warning-soft text-warning",
        status === "failed" && "border-danger/30 bg-danger-soft text-danger",
        status === "paused" && "border-line-strong bg-surface-muted text-ink-soft",
        (status === "draft" || status === "pending") && "border-line bg-surface-muted text-muted"
      )}
    >
      {status}
    </span>
  );
}

