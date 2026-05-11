import * as React from "react";
import { cn } from "../../lib/utils";

export function Textarea({ className, ...props }: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      className={cn("min-h-28 w-full resize-y rounded-md border border-line bg-surface px-3 py-2 font-mono text-sm leading-6 text-ink shadow-sm focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-accent/20", className)}
      {...props}
    />
  );
}

