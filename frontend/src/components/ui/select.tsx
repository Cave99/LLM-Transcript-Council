import * as React from "react";
import { cn } from "../../lib/utils";

export function Select({ className, ...props }: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      className={cn("min-h-10 w-full rounded-md border border-line bg-surface px-3 text-sm text-ink shadow-sm focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-accent/20", className)}
      {...props}
    />
  );
}

