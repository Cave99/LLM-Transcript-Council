import { useEffect, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { AlertTriangle, Play } from "lucide-react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { client } from "../../api/client";
import { queryClient } from "../../api/queries";
import type { ValidationResult } from "../../api/types";
import { StatusPill } from "../../components/status-pill";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { GraphCanvasProvider } from "./graph-canvas";
import { GraphInspector } from "./graph-inspector";
import { GraphSpecEditor } from "./graph-spec-editor";
import type { GraphLayout, GraphSpec } from "./graph-spec-types";
import { planStats } from "./graph-spec-types";

export function GraphDetailPage() {
  const navigate = useNavigate();
  const graphId = Number(useParams().graphId);
  const { data, isLoading, error } = useQuery({ queryKey: ["graph", graphId], queryFn: () => client.graph(graphId), enabled: Number.isFinite(graphId) });
  const [draft, setDraft] = useState("");
  const [validation, setValidation] = useState<ValidationResult | null>(null);
  const [selectedId, setSelectedId] = useState<string>("dataset");
  const [isRenaming, setIsRenaming] = useState(false);
  const [localLayout, setLocalLayout] = useState<GraphLayout>({});

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["graph", graphId] });
  const update = useMutation({ mutationFn: (body: { name?: string; spec?: Record<string, unknown>; layout?: Record<string, unknown> }) => client.updateGraph(graphId, body), onSuccess: () => { invalidate(); setIsRenaming(false); } });
  const updateLayout = useMutation({ mutationFn: (layout: GraphLayout) => client.updateGraph(graphId, { layout }) });
  const validate = useMutation({ mutationFn: async (text: string) => client.validateSpec(JSON.parse(text)), onSuccess: setValidation });
  const saveSpec = useMutation({
    mutationFn: async (text: string) => client.replaceSpec(graphId, JSON.parse(text)),
    onSuccess: (next) => {
      setDraft(JSON.stringify(next.spec, null, 2));
      setValidation(null);
      invalidate();
    },
  });
  const launch = useMutation({
    mutationFn: (mode: "test" | "full") => client.launchGraph(graphId, mode, 5),
    onSuccess: (run) => navigate(`/graph-runs/${run.id}`),
  });

  useEffect(() => {
    if (data) setLocalLayout(data.layout as GraphLayout);
  }, [data?.graph.id, data?.layout]);

  if (isLoading) return <p className="text-sm text-muted">Loading graph...</p>;
  if (error || !data) return <p className="text-sm text-danger">{String(error || "Graph not found")}</p>;

  const spec = data.spec as GraphSpec;
  const layout = Object.keys(localLayout).length ? localLayout : data.layout;
  const specText = draft || JSON.stringify(data.spec, null, 2);
  const saveGraphSpec = (nextSpec: GraphSpec, nextLayout = layout) => {
    setDraft(JSON.stringify(nextSpec, null, 2));
    update.mutate({ spec: nextSpec as unknown as Record<string, unknown>, layout: nextLayout });
  };
  const saveGraphLayout = (nextLayout: GraphLayout) => {
    setLocalLayout(nextLayout);
    updateLayout.mutate(nextLayout);
  };
  const handleSpecParseError = (exc: unknown) => {
    setValidation({ valid: false, errors: [{ code: "invalid_json", path: "$", message: String(exc) }], warnings: [] });
  };
  const jumpToPath = (path: string) => {
    const textarea = document.getElementById("spec-textarea") as HTMLTextAreaElement | null;
    if (!textarea) return;
    let el: HTMLElement | null = textarea;
    while (el) {
      if (el.tagName === "DETAILS" && !(el as HTMLDetailsElement).open) (el as HTMLDetailsElement).open = true;
      el = el.parentElement;
    }
    const lines = specText.split("\n");
    const parts = path.replace("$.", "").split(/[.\[\]]/).filter(Boolean);
    const lineIndex = lines.findIndex((line) => parts.every((part) => line.trim().includes(part)));
    const targetLine = Math.max(0, lineIndex);
    const lineHeight = Number.parseFloat(getComputedStyle(textarea).lineHeight) || 15;
    textarea.focus();
    textarea.scrollTop = Math.max(0, targetLine - 1) * lineHeight;
    const start = lines.slice(0, targetLine).join("\n").length + (targetLine > 0 ? 1 : 0);
    const end = start + lines[targetLine].length;
    textarea.setSelectionRange(start, end);
    setTimeout(() => textarea.setSelectionRange(end, end), 1500);
  };

  return (
    <div className="flex min-h-[calc(100vh-170px)] flex-col gap-6 pb-20">
      <section className="grid gap-4 border-b border-line pb-6 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-end">
        <div className="grid gap-3">
          <div className="flex items-center gap-3">
            {isRenaming ? (
              <form
                className="flex max-w-md gap-2"
                onSubmit={(event) => {
                  event.preventDefault();
                  const name = String(new FormData(event.currentTarget).get("name") || "").trim();
                  if (name) update.mutate({ name });
                }}
              >
                <Input name="name" defaultValue={data.graph.name} autoFocus onBlur={() => setIsRenaming(false)} />
                <Button variant="subtle">Rename</Button>
              </form>
            ) : (
              <button type="button" className="text-3xl font-extrabold transition hover:text-accent" onClick={() => setIsRenaming(true)} title="Click to rename">
                {data.graph.name}
              </button>
            )}
            <StatusPill status={data.graph.status} />
          </div>
          <p className="max-w-2xl text-sm text-muted">Edit the draft, inspect the generated plan, and launch a test or full run when the graph is ready.</p>
        </div>
        <div className="flex items-end justify-end">
          <Link className="text-xs text-muted hover:text-accent" to={`/projects/${data.graph.project_id}`}>Back to project</Link>
        </div>
      </section>

      <div className="grid flex-1 gap-5">
        <GraphCanvasProvider
          spec={spec}
          nodes={data.nodes}
          edges={data.edges}
          layout={layout}
          selectedId={selectedId}
          onSelect={setSelectedId}
          onSpecChange={saveGraphSpec}
          onLayoutChange={saveGraphLayout}
          inspector={<GraphInspector spec={spec} selectedId={selectedId} onSelect={setSelectedId} onChange={saveGraphSpec} />}
        />
        <GraphSpecEditor
          specText={specText}
          validation={validation}
          onDraftChange={setDraft}
          onJumpToPath={jumpToPath}
          onValidate={() => { try { validate.mutate(specText); } catch (exc) { handleSpecParseError(exc); } }}
          onSave={() => { try { saveSpec.mutate(specText); } catch (exc) { handleSpecParseError(exc); } }}
        />
      </div>

      <section className="fixed bottom-0 left-0 right-0 z-30 border-t border-line bg-surface shadow-[0_-4px_16px_oklch(0.22_0.012_215/0.05)]">
        <div className="mx-auto grid w-[min(1480px,calc(100vw-24px))] gap-3 px-4 py-4">
          <div className="flex flex-wrap items-center gap-3">
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted">
              <span className="font-semibold text-ink">Plan</span>
              <span>{data.plan.transcript_count} item{data.plan.transcript_count === 1 ? "" : "s"}</span>
              {planStats(data.plan).map(([label, value]) => (
                <span key={label} className="whitespace-nowrap">
                  <span className="text-line">·</span> {label} <strong className="text-ink-soft">{Number(value).toLocaleString()}</strong>
                </span>
              ))}
            </div>
            <div className="ml-auto flex items-center gap-2">
              {data.latest_run ? <Button type="button" variant="subtle" onClick={() => navigate(`/graph-runs/${data.latest_run?.id}`)}>Latest Run</Button> : null}
              <Button type="button" variant="subtle" onClick={() => launch.mutate("test")}>Test Run</Button>
              <Button type="button" onClick={() => launch.mutate("full")}><Play size={14} />Launch</Button>
            </div>
          </div>
          {data.plan.warnings.length > 0 ? (
            <div className="flex flex-col gap-1">
              {data.plan.warnings.map((warning) => (
                <p key={warning} className="flex items-start gap-1.5 text-xs text-warning">
                  <AlertTriangle size={13} className="mt-0.5 shrink-0" />
                  {warning}
                </p>
              ))}
            </div>
          ) : null}
        </div>
      </section>
    </div>
  );
}
