import { useEffect, useState } from "react";
import type { GraphNodeDto } from "../../api/types";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Select } from "../../components/ui/select";
import { Textarea } from "../../components/ui/textarea";
import { Sheet } from "../../components/ui/sheet";

export function NodeEditor({ node, onClose, onSave, onDelete }: { node: GraphNodeDto | null; onClose: () => void; onSave: (node: GraphNodeDto, title: string, body: string, config: Record<string, unknown>) => void; onDelete: (node: GraphNodeDto) => void }) {
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [config, setConfig] = useState<Record<string, unknown>>({});

  useEffect(() => {
    if (!node) return;
    setTitle(node.title);
    setBody(node.body);
    setConfig(node.config);
  }, [node]);

  if (!node) return <Sheet title="Node" open={false} onClose={onClose}>{null}</Sheet>;

  const setConfigValue = (key: string, value: unknown) => setConfig((current) => ({ ...current, [key]: value }));

  return (
    <Sheet title={`Edit ${node.kind}`} open={Boolean(node)} onClose={onClose}>
      <form
        className="grid gap-4"
        onSubmit={(event) => {
          event.preventDefault();
          onSave(node, title, body, config);
        }}
      >
        <label className="grid gap-1 text-sm font-semibold">
          Title
          <Input value={title} onChange={(event) => setTitle(event.target.value)} />
        </label>

        {node.kind === "dataset" ? (
          <>
            <label className="grid gap-1 text-sm font-semibold">
              Source
              <Select value={String(config.source_type || "markdown")} onChange={(event) => setConfigValue("source_type", event.target.value)}>
                <option value="markdown">Markdown folder</option>
                <option value="csv">CSV</option>
              </Select>
            </label>
            <label className="grid gap-1 text-sm font-semibold">
              Path
              <Input value={String(config.path || "")} onChange={(event) => setConfigValue("path", event.target.value)} />
            </label>
            <label className="grid gap-1 text-sm font-semibold">
              Sample size
              <Input value={String(config.sample_size || "")} onChange={(event) => setConfigValue("sample_size", event.target.value)} />
            </label>
          </>
        ) : null}

        {node.kind === "model" ? (
          <>
            <label className="grid gap-1 text-sm font-semibold">
              Role
              <Select value={String(config.role || "generator")} onChange={(event) => setConfigValue("role", event.target.value)}>
                <option value="generator">Generator</option>
                <option value="judge">Judge</option>
              </Select>
            </label>
            <label className="grid gap-1 text-sm font-semibold">
              Model ID
              <Input value={String(config.model_id || "")} onChange={(event) => setConfigValue("model_id", event.target.value)} placeholder="openai/gpt-4o-mini" />
            </label>
            <label className="grid gap-1 text-sm font-semibold">
              Temperature
              <Input value={String(config.temperature ?? "")} onChange={(event) => setConfigValue("temperature", event.target.value)} />
            </label>
          </>
        ) : null}

        {node.kind === "constant" ? (
          <label className="grid gap-1 text-sm font-semibold">
            Socket
            <Input value={String(config.socket || "")} onChange={(event) => setConfigValue("socket", event.target.value)} />
          </label>
        ) : null}

        {node.kind === "prompt" ? (
          <label className="grid gap-1 text-sm font-semibold">
            Upstream output mode
            <Select value={String(config.upstream_mode || "raw")} onChange={(event) => setConfigValue("upstream_mode", event.target.value)}>
              <option value="raw">Raw text</option>
              <option value="json">Repaired JSON</option>
            </Select>
          </label>
        ) : null}

        {node.kind === "judge" ? (
          <>
            <label className="grid gap-1 text-sm font-semibold">
              Pairing sample %
              <Input value={String(config.pairing_sample_pct || "100")} onChange={(event) => setConfigValue("pairing_sample_pct", event.target.value)} />
            </label>
            <label className="grid gap-1 text-sm font-semibold">
              Winner key
              <Input value={String(config.winner_key || "winner")} onChange={(event) => setConfigValue("winner_key", event.target.value)} />
            </label>
            <label className="grid gap-1 text-sm font-semibold">
              Reasoning key
              <Input value={String(config.reasoning_key || "reasoning")} onChange={(event) => setConfigValue("reasoning_key", event.target.value)} />
            </label>
          </>
        ) : null}

        {node.kind !== "dataset" && node.kind !== "model" ? (
          <label className="grid gap-1 text-sm font-semibold">
            Body
            <Textarea rows={12} value={body} onChange={(event) => setBody(event.target.value)} />
          </label>
        ) : null}

        <div className="flex justify-between gap-2 border-t border-line pt-4">
          <Button type="button" variant="danger" onClick={() => onDelete(node)}>Delete</Button>
          <div className="flex gap-2">
            <Button type="button" variant="subtle" onClick={onClose}>Cancel</Button>
            <Button type="submit">Save</Button>
          </div>
        </div>
      </form>
    </Sheet>
  );
}
