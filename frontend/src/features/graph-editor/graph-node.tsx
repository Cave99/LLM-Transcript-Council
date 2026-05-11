import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { Handle, Position, type NodeProps } from "reactflow";
import { Database, FileText, Gavel, MessageSquare, Save, Settings, Trash2 } from "lucide-react";
import type { GraphNodeDto, GraphProgress } from "../../api/types";
import { StatusPill } from "../../components/status-pill";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Select } from "../../components/ui/select";
import { Textarea } from "../../components/ui/textarea";

const icons = {
  dataset: Database,
  prompt: MessageSquare,
  constant: FileText,
  model: Settings,
  judge: Gavel
};

type GraphNodeData = {
  node: GraphNodeDto;
  progress?: GraphProgress;
  onSave: (node: GraphNodeDto, title: string, body: string, config: Record<string, unknown>) => void;
  onDelete: (node: GraphNodeDto) => void;
};

export function GraphNodeCard({ data }: NodeProps<GraphNodeData>) {
  const node = data.node;
  const Icon = icons[node.kind as keyof typeof icons] ?? FileText;
  const [title, setTitle] = useState(node.title);
  const [body, setBody] = useState(node.body);
  const [config, setConfig] = useState<Record<string, unknown>>(node.config);

  useEffect(() => {
    setTitle(node.title);
    setBody(node.body);
    setConfig(node.config);
  }, [node]);

  const setConfigValue = (key: string, value: unknown) => setConfig((current) => ({ ...current, [key]: value }));
  const hasBody = node.kind !== "dataset" && node.kind !== "model";
  const nodeWidth = hasBody ? 970 : 600;

  return (
    <form
      className="relative grid overflow-visible rounded-lg border border-line bg-surface shadow-sm"
      style={{ width: nodeWidth }}
      onSubmit={(event) => {
        event.preventDefault();
        data.onSave(node, title, body, config);
      }}
    >
      <NodeHeader icon={<Icon size={15} className="text-accent" />} title={node.kind} subtitle={node.title}>
        {data.progress && data.progress.total > 0 ? (
          <span className="flex items-center gap-2 text-xs text-muted">
            <StatusPill status={data.progress.failed ? "failed" : data.progress.complete === data.progress.total ? "complete" : "running"} />
            {data.progress.complete}/{data.progress.total}
          </span>
        ) : null}
      </NodeHeader>

      <div className={["grid gap-0", hasBody ? "grid-cols-[150px_300px_minmax(320px,1fr)_160px]" : "grid-cols-[150px_minmax(280px,1fr)_150px]"].join(" ")}>
        <SocketRail side="input" sockets={node.input_sockets} />

        <section className="nodrag nowheel grid content-start gap-3 border-r border-line bg-surface-muted/45 p-4">
          <Field label="Title">
            <Input value={title} onChange={(event) => setTitle(event.target.value)} />
          </Field>
          <ConfigFields node={node} config={config} setConfigValue={setConfigValue} />
        </section>

        {hasBody ? (
          <section className="nodrag nowheel grid min-h-[300px] grid-rows-[auto_1fr] gap-2 p-4">
            <div>
              <h3 className="text-sm font-bold">Body</h3>
              <p className="text-xs text-muted">Use sockets like {"{{ transcript }}"} or {"{{ previous_output }}"}.</p>
            </div>
            <Textarea className="h-full min-h-[220px] resize-none" value={body} onChange={(event) => setBody(event.target.value)} />
          </section>
        ) : null}

        <SocketRail side="output" sockets={node.output_sockets} />
      </div>

      <footer className="nodrag nowheel flex justify-between gap-2 border-t border-line bg-surface-muted px-4 py-3">
        <Button type="button" variant="danger" onClick={() => data.onDelete(node)}>
          <Trash2 size={15} />
          Delete
        </Button>
        <Button type="submit">
          <Save size={15} />
          Save
        </Button>
      </footer>
    </form>
  );
}

function NodeHeader({ icon, title, subtitle, children }: { icon: ReactNode; title: string; subtitle: string; children: ReactNode }) {
  return (
    <div className="flex cursor-grab items-center justify-between gap-3 border-b border-line px-3 py-2 active:cursor-grabbing">
      <div className="flex min-w-0 items-center gap-2">
        {icon}
        <div className="min-w-0">
          <strong className="block truncate text-sm">{title}</strong>
          <span className="block truncate text-[10px] font-bold uppercase tracking-wide text-muted">{subtitle}</span>
        </div>
      </div>
      <div className="nodrag nowheel flex shrink-0 items-center gap-2">{children}</div>
    </div>
  );
}

function SocketRail({ side, sockets }: { side: "input" | "output"; sockets: string[] }) {
  const isInput = side === "input";
  return (
    <section className={[
      "grid content-start gap-3 p-4",
      isInput ? "border-r border-line" : "border-l border-line"
    ].join(" ")}>
      <span className="text-[10px] font-bold uppercase tracking-wide text-ink-soft">{isInput ? "Inputs" : "Outputs"}</span>
      {sockets.length ? (
        <div className="grid gap-2">
          {sockets.map((socket) => (
            <div key={`${side}-row-${socket}`} className={["relative min-h-7", isInput ? "pl-6 text-left" : "pr-6 text-right"].join(" ")}>
              {isInput ? <Handle type="target" id={socket} position={Position.Left} className="!left-[-17px] !top-3.5" /> : null}
              <span className="inline-block max-w-[118px] truncate rounded bg-surface-raised px-2 py-1 text-xs font-semibold text-ink-soft shadow-sm">{socket}</span>
              {!isInput ? <Handle type="source" id={socket} position={Position.Right} className="!right-[-17px] !top-3.5" /> : null}
            </div>
          ))}
        </div>
      ) : (
        <span className="text-xs text-muted">None</span>
      )}
    </section>
  );
}

function ConfigFields({ node, config, setConfigValue }: { node: GraphNodeDto; config: Record<string, unknown>; setConfigValue: (key: string, value: unknown) => void }) {
  if (node.kind === "dataset") {
    return (
      <>
        <Field label="Source">
          <Select value={String(config.source_type || "markdown")} onChange={(event) => setConfigValue("source_type", event.target.value)}>
            <option value="markdown">Markdown folder</option>
            <option value="csv">CSV</option>
          </Select>
        </Field>
        <Field label="Path">
          <Input value={String(config.path || "")} onChange={(event) => setConfigValue("path", event.target.value)} />
        </Field>
        <Field label="Sample size">
          <Input value={String(config.sample_size || "")} onChange={(event) => setConfigValue("sample_size", event.target.value)} />
        </Field>
      </>
    );
  }
  if (node.kind === "model") {
    return (
      <>
        <Field label="Role">
          <Select value={String(config.role || "generator")} onChange={(event) => setConfigValue("role", event.target.value)}>
            <option value="generator">Generator</option>
            <option value="judge">Judge</option>
          </Select>
        </Field>
        <Field label="Model ID">
          <Input value={String(config.model_id || "")} onChange={(event) => setConfigValue("model_id", event.target.value)} placeholder="openai/gpt-4o-mini" />
        </Field>
        <Field label="Temperature">
          <Input value={String(config.temperature ?? "")} onChange={(event) => setConfigValue("temperature", event.target.value)} />
        </Field>
      </>
    );
  }
  if (node.kind === "constant") {
    return (
      <Field label="Socket">
        <Input value={String(config.socket || "")} onChange={(event) => setConfigValue("socket", event.target.value)} />
      </Field>
    );
  }
  if (node.kind === "prompt") {
    return (
      <Field label="Upstream output mode">
        <Select value={String(config.upstream_mode || "raw")} onChange={(event) => setConfigValue("upstream_mode", event.target.value)}>
          <option value="raw">Raw text</option>
          <option value="json">Repaired JSON</option>
        </Select>
      </Field>
    );
  }
  if (node.kind === "judge") {
    return (
      <>
        <Field label="Pairing sample %">
          <Input value={String(config.pairing_sample_pct || "100")} onChange={(event) => setConfigValue("pairing_sample_pct", event.target.value)} />
        </Field>
        <Field label="Winner key">
          <Input value={String(config.winner_key || "winner")} onChange={(event) => setConfigValue("winner_key", event.target.value)} />
        </Field>
        <Field label="Reasoning key">
          <Input value={String(config.reasoning_key || "reasoning")} onChange={(event) => setConfigValue("reasoning_key", event.target.value)} />
        </Field>
      </>
    );
  }
  return null;
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="grid gap-1 text-xs font-bold text-ink-soft">
      {label}
      {children}
    </label>
  );
}
