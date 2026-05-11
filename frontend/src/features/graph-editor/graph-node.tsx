import { Handle, Position, type NodeProps } from "reactflow";
import { Database, FileText, Gavel, MessageSquare, Settings } from "lucide-react";
import type { GraphNodeDto, GraphProgress } from "../../api/types";
import { StatusPill } from "../../components/status-pill";

const icons = {
  dataset: Database,
  prompt: MessageSquare,
  constant: FileText,
  model: Settings,
  judge: Gavel
};

export function GraphNodeCard({ data }: NodeProps<{ node: GraphNodeDto; progress?: GraphProgress; onEdit: (node: GraphNodeDto) => void }>) {
  const node = data.node;
  const Icon = icons[node.kind as keyof typeof icons] ?? FileText;
  return (
    <div className="min-w-[260px] rounded-lg border border-line bg-surface shadow-sm">
      <div className="flex items-center justify-between gap-3 border-b border-line px-3 py-2">
        <div className="flex min-w-0 items-center gap-2">
          <Icon size={15} className="text-accent" />
          <strong className="truncate text-sm">{node.title}</strong>
        </div>
        <button className="text-xs font-semibold text-accent hover:text-accent-hover" onClick={() => data.onEdit(node)}>
          Edit
        </button>
      </div>
      <div className="grid gap-2 p-3 text-xs text-muted">
        <span className="uppercase tracking-wide">{node.kind}</span>
        {node.kind === "model" ? <span>{String(node.config.model_id || "No model ID")}</span> : null}
        {node.kind === "dataset" ? <span>{String(node.config.path || "No path")}</span> : null}
        {data.progress && data.progress.total > 0 ? (
          <span className="flex items-center gap-2">
            <StatusPill status={data.progress.failed ? "failed" : data.progress.complete === data.progress.total ? "complete" : "running"} />
            {data.progress.complete}/{data.progress.total}
          </span>
        ) : null}
      </div>
      {node.input_sockets.map((socket, index) => (
        <Handle key={`in-${socket}`} type="target" id={socket} position={Position.Left} style={{ top: 54 + index * 18 }} />
      ))}
      {node.output_sockets.map((socket, index) => (
        <Handle key={`out-${socket}`} type="source" id={socket} position={Position.Right} style={{ top: 54 + index * 18 }} />
      ))}
    </div>
  );
}

