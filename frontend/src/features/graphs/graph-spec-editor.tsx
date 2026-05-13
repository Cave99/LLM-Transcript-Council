import { Braces, Save } from "lucide-react";
import type { ValidationResult } from "../../api/types";
import { DataTable } from "../../components/data-table";
import { Button } from "../../components/ui/button";
import { Textarea } from "../../components/ui/textarea";

export function GraphSpecEditor({
  specText,
  validation,
  onDraftChange,
  onValidate,
  onSave,
  onJumpToPath,
}: {
  specText: string;
  validation: ValidationResult | null;
  onDraftChange: (value: string) => void;
  onValidate: () => void;
  onSave: () => void;
  onJumpToPath: (path: string) => void;
}) {
  return (
    <details className="panel overflow-hidden">
      <summary className="flex h-[57px] shrink-0 cursor-pointer items-center gap-2 border-b border-line bg-surface-muted px-4 text-sm font-bold [&::-webkit-details-marker]:hidden">
        <Braces size={15} className="text-accent" />
        Spec JSON
      </summary>
      <div className="grid gap-3 p-4">
        <Textarea id="spec-textarea" className="h-[200px] resize-none font-mono text-xs" value={specText} onChange={(event) => onDraftChange(event.target.value)} />
        {validation ? <ValidationPanel result={validation} onJumpToPath={onJumpToPath} /> : null}
        <div className="flex gap-2">
          <Button type="button" variant="subtle" onClick={onValidate}>Validate</Button>
          <Button type="button" onClick={onSave}>
            <Save size={15} />
            Save Spec
          </Button>
        </div>
      </div>
    </details>
  );
}

function ValidationPanel({ result, onJumpToPath }: { result: ValidationResult; onJumpToPath?: (path: string) => void }) {
  const rows = [...result.errors.map((item) => ({ ...item, level: "Error" })), ...result.warnings.map((item) => ({ ...item, level: "Warning" }))];
  if (!rows.length) return <p className="rounded-md border border-success/30 bg-success-soft p-2 text-sm text-success">Spec is valid.</p>;
  return (
    <DataTable>
      <table className="w-full text-xs">
        <tbody>
          {rows.map((row) => (
            <tr key={`${row.level}-${row.path}-${row.code}`} className="border-b border-line last:border-0">
              <td className="p-2 font-bold">{row.level}</td>
              <td className="p-2 font-mono" onClick={() => onJumpToPath?.(row.path)} title={`Jump to ${row.path}`}>{row.path}</td>
              <td className="p-2">{row.message}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </DataTable>
  );
}
