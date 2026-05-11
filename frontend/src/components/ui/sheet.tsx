import * as React from "react";
import { X } from "lucide-react";
import { Button } from "./button";

export function Sheet({ title, open, onClose, children }: { title: string; open: boolean; onClose: () => void; children: React.ReactNode }) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50">
      <button className="absolute inset-0 bg-ink/20" aria-label="Close panel" onClick={onClose} />
      <aside className="absolute right-0 top-0 h-full w-[min(520px,100vw)] overflow-y-auto border-l border-line bg-surface p-5 shadow-xl">
        <div className="mb-4 flex items-center justify-between gap-3">
          <h2 className="text-base font-bold">{title}</h2>
          <Button type="button" variant="ghost" onClick={onClose} aria-label="Close">
            <X size={16} />
          </Button>
        </div>
        {children}
      </aside>
    </div>
  );
}
