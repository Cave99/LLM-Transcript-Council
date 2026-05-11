import * as React from "react";
import { cn } from "../../lib/utils";

type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "default" | "subtle" | "danger" | "ghost";
};

export function Button({ className, variant = "default", ...props }: ButtonProps) {
  return (
    <button
      className={cn(
        "inline-flex min-h-9 items-center justify-center gap-2 rounded-md border px-3 py-1.5 text-sm font-semibold transition focus-visible:outline-none focus-visible:ring-4 disabled:pointer-events-none disabled:opacity-50",
        variant === "default" && "border-accent bg-accent text-white hover:bg-accent-hover focus-visible:ring-accent/20",
        variant === "subtle" && "border-line bg-surface text-ink hover:border-line-strong hover:bg-surface-muted focus-visible:ring-accent/20",
        variant === "danger" && "border-danger/30 bg-danger-soft text-danger hover:border-danger/50 focus-visible:ring-danger/20",
        variant === "ghost" && "border-transparent bg-transparent text-ink-soft hover:bg-surface-muted hover:text-ink focus-visible:ring-accent/20",
        className
      )}
      {...props}
    />
  );
}

