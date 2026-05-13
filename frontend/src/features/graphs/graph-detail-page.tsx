import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import ReactFlow, { Background, Controls, Handle, Position, ReactFlowProvider, useNodesState, useReactFlow, type Connection, type Edge, type Node } from "reactflow";
import { AlertTriangle, Bot, Braces, Database, Gavel, GitBranch, Play, Plus, Save, Trash2, X } from "lucide-react";
import { client } from "../../api/client";
import { queryClient } from "../../api/queries";
import type { GraphPlanDto, SemanticNodeDto, ValidationResult } from "../../api/types";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Select } from "../../components/ui/select";
import { Textarea } from "../../components/ui/textarea";
import { StatusPill } from "../../components/status-pill";
import { DataTable } from "../../components/data-table";

const nodeTypes = { semantic: SemanticNode };

type GraphSpec = {
  version: 1;
  dataset: { provider: "markdown_folder" | "csv"; config: Record<string, unknown> };
  constants?: Record<string, string>;
  stages: StageSpec[];
  evaluators: EvaluatorSpec[];
};

type StageSpec = {
  id: string;
  title?: string;
  fanout?: "matrix";
  upstream_output?: "raw" | "json";
  candidates: CandidateSpec[];
};

type CandidateSpec = {
  id: string;
  title?: string;
  model?: string;
  prompt_path?: string | null;
  prompt_inline?: string | null;
  params?: { temperature?: number; retry_count?: number; reasoning_effort?: string | null };
};

type EvaluatorSpec = {
  id: string;
  title?: string;
  type: "llm_pairwise" | "human_pairwise";
  target_stage: string;
  model?: string;
  prompt_path?: string | null;
  prompt_inline?: string | null;
  params?: { temperature?: number; retry_count?: number; reasoning_effort?: string | null };
  pairing: { sample_pct?: number; swap?: boolean; seed?: string | null };
  output?: { winner_key?: string; reasoning_key?: string };
};

export function GraphDetailPage() {
  return (
    <ReactFlowProvider>
      <GraphDetailInner />
    </ReactFlowProvider>
  );
}

function GraphDetailInner() {
  const navigate = useNavigate();
  const { screenToFlowPosition } = useReactFlow();
  const graphId = Number(useParams().graphId);
  const { data, isLoading, error } = useQuery({ queryKey: ["graph", graphId], queryFn: () => client.graph(graphId), enabled: Number.isFinite(graphId) });
  const [draft, setDraft] = useState("");
  const [validation, setValidation] = useState<ValidationResult | null>(null);
  const jumpToPath = (path: string) => {
    const textarea = document.getElementById("spec-textarea") as HTMLTextAreaElement | null;
    if (!textarea) return;
    let el: HTMLElement | null = textarea;
    while (el) {
      if (el.tagName === "DETAILS" && !(el as HTMLDetailsElement).open) { (el as HTMLDetailsElement).open = true; }
      el = el.parentElement;
    }
    const lines = specText.split("\n");
    const parts = path.replace("$.", "").split(/[.\[\]]/).filter(Boolean);
    let lineIndex = 0;
    for (let i = 0; i < lines.length; i++) {
      const trimmed = lines[i].trim();
      if (parts.every((p) => trimmed.includes(p))) { lineIndex = i; break; }
    }
    const lineHeight = Number.parseFloat(getComputedStyle(textarea).lineHeight) || 15;
    textarea.focus();
    textarea.scrollTop = Math.max(0, lineIndex - 1) * lineHeight;
    const start = lines.slice(0, lineIndex).join("\n").length + 1;
    const end = start + lines[lineIndex].length;
    textarea.setSelectionRange(start, end);
    setTimeout(() => textarea.setSelectionRange(end, end), 1500);
  };
  const [selectedId, setSelectedId] = useState<string>("dataset");
  const [isRenaming, setIsRenaming] = useState(false);
  const [localLayout, setLocalLayout] = useState<Record<string, { x: number; y: number }>>({});
  const [flowNodes, setFlowNodes, onNodesChange] = useNodesState([]);

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["graph", graphId] });
  const update = useMutation({ mutationFn: (body: { name?: string; spec?: Record<string, unknown>; layout?: Record<string, unknown> }) => client.updateGraph(graphId, body), onSuccess: () => { invalidate(); setIsRenaming(false); } });
  const updateLayout = useMutation({ mutationFn: (layout: Record<string, { x: number; y: number }>) => client.updateGraph(graphId, { layout }) });
  const validate = useMutation({
    mutationFn: async (text: string) => client.validateSpec(JSON.parse(text)),
    onSuccess: setValidation,
  });
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
    if (data) setLocalLayout(data.layout as Record<string, { x: number; y: number }>);
  }, [data?.graph.id, data?.layout]);
  useEffect(() => {
    if (!data) return;
    setFlowNodes(data.nodes.map((node) => ({
      id: node.id,
      type: "semantic",
      position: (data.layout as Record<string, { x: number; y: number }>)[node.id] || { x: node.x, y: node.y },
      data: {},
      dragHandle: ".semantic-node-drag-handle",
      draggable: true
    })));
  }, [data?.graph.id, data?.nodes, data?.layout, setFlowNodes]);

  if (isLoading) return <p className="text-sm text-muted">Loading graph...</p>;
  if (error || !data) return <p className="text-sm text-danger">{String(error || "Graph not found")}</p>;

  const spec = data.spec as GraphSpec;
  const layout = Object.keys(localLayout).length ? localLayout : data.layout;
  const specText = draft || JSON.stringify(data.spec, null, 2);
  const updateStage = (stageId: string, next: StageSpec) => saveGraphSpec({ ...spec, stages: spec.stages.map((item) => item.id === stageId ? next : item) });
  const updateEvaluator = (evaluatorId: string, next: EvaluatorSpec) => saveGraphSpec({ ...spec, evaluators: spec.evaluators.map((item) => item.id === evaluatorId ? next : item) });
  const updateCandidate = (stageId: string, candidateId: string, next: CandidateSpec) => saveGraphSpec({
    ...spec,
    stages: spec.stages.map((stage) => stage.id === stageId ? {
      ...stage,
      candidates: stage.candidates.map((candidate) => candidate.id === candidateId ? next : candidate),
    } : stage),
  });
  const semanticNodes: Node[] = data.nodes.map((node) => {
    const controlled = flowNodes.find((flowNode) => flowNode.id === node.id);
    return {
    id: node.id,
    type: "semantic",
    position: controlled?.position || layout[node.id] || { x: node.x, y: node.y },
    data: { node, spec, onSelect: setSelectedId, onStageChange: updateStage, onCandidateChange: updateCandidate, onEvaluatorChange: updateEvaluator },
    dragHandle: ".semantic-node-drag-handle",
    draggable: true,
    selected: controlled?.selected,
    dragging: controlled?.dragging,
    width: controlled?.width,
    height: controlled?.height,
  };
  });
  const edges: Edge[] = data.edges.map((edge) => ({ id: edge.id, source: edge.source, target: edge.target, animated: false }));
  const saveGraphSpec = (nextSpec: GraphSpec, nextLayout = layout) => {
    setDraft(JSON.stringify(nextSpec, null, 2));
    update.mutate({ spec: nextSpec as unknown as Record<string, unknown>, layout: nextLayout });
  };
  const positionForNode = (nodeId: string) => {
    const controlled = flowNodes.find((node) => node.id === nodeId);
    const semantic = data.nodes.find((node) => node.id === nodeId);
    return controlled?.position || layout[nodeId] || (semantic ? { x: semantic.x, y: semantic.y } : undefined);
  };
  const positionRightOf = (sourceIds: string[], fallback = { x: 40, y: 160 }) => {
    const positions = sourceIds.map(positionForNode).filter((position): position is { x: number; y: number } => Boolean(position));
    if (!positions.length) return { x: fallback.x + 360, y: fallback.y };
    return {
      x: Math.round(Math.max(...positions.map((position) => position.x)) + 360),
      y: Math.round(positions.reduce((sum, position) => sum + position.y, 0) / positions.length),
    };
  };
  const createSemanticNode = (kind: "stage" | "llm_pairwise" | "human_pairwise", position: { x: number; y: number }) => {
    if (kind === "stage") {
      const id = uniqueId("stage", spec.stages.map((stage) => stage.id));
      saveGraphSpec({ ...spec, stages: [...spec.stages, newStage(id)] }, { ...layout, [id]: { x: Math.round(position.x), y: Math.round(position.y) } });
      setSelectedId(id);
      return;
    }
    const id = uniqueId(kind === "human_pairwise" ? "human_review" : "judge", spec.evaluators.map((item) => item.id));
    saveGraphSpec({ ...spec, evaluators: [...spec.evaluators, newEvaluator(id, kind, spec.stages.at(-1)?.id || "")] }, { ...layout, [id]: { x: Math.round(position.x), y: Math.round(position.y) } });
    setSelectedId(id);
  };
  const connectSemanticNodes = (connection: Connection) => {
    if (!connection.source || !connection.target || connection.source === connection.target) return;
    const sourceStage = spec.stages.find((stage) => stage.id === connection.source);
    const targetStage = spec.stages.find((stage) => stage.id === connection.target);
    const sourceEvaluator = spec.evaluators.find((evaluator) => evaluator.id === connection.source);
    const targetEvaluator = spec.evaluators.find((evaluator) => evaluator.id === connection.target);
    if (sourceStage && targetEvaluator) {
      saveGraphSpec({ ...spec, evaluators: spec.evaluators.map((item) => item.id === targetEvaluator.id ? { ...item, target_stage: sourceStage.id } : item) });
      return;
    }
    if (sourceEvaluator && targetStage) {
      saveGraphSpec({ ...spec, evaluators: spec.evaluators.map((item) => item.id === sourceEvaluator.id ? { ...item, target_stage: targetStage.id } : item) });
      return;
    }
    if (sourceStage && targetStage) {
      const withoutSource = spec.stages.filter((stage) => stage.id !== sourceStage.id);
      const targetIndex = withoutSource.findIndex((stage) => stage.id === targetStage.id);
      const nextStages = [...withoutSource.slice(0, targetIndex), sourceStage, ...withoutSource.slice(targetIndex)];
      saveGraphSpec({ ...spec, stages: nextStages });
    }
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
              <button
                type="button"
                className="text-3xl font-extrabold transition hover:text-accent"
                onClick={() => setIsRenaming(true)}
                title="Click to rename"
              >
                {data.graph.name}
              </button>
            )}
            <StatusPill status={data.graph.status} />
          </div>
          <p className="max-w-2xl text-sm text-muted">
            Edit the draft, inspect the generated plan, and launch a test or full run when the graph is ready.
          </p>
        </div>
        <div className="flex items-end justify-end">
          <Link className="text-xs text-muted hover:text-accent" to={`/projects/${data.graph.project_id}`}>Back to project</Link>
        </div>
      </section>

      <div className="grid flex-1 gap-5">
        <section className="panel grid overflow-hidden lg:grid-cols-[minmax(0,1fr)_300px]">
          <div className="min-w-0">
            <div className="flex h-[57px] shrink-0 items-center justify-between gap-4 border-b border-line bg-surface-muted px-4">
              <div className="grid gap-0.5">
                <h2 className="text-sm font-bold">Semantic graph</h2>
                <p className="text-xs text-muted">Drag nodes to rearrange, connect outputs to reroute stages and judges.</p>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button type="button" variant="subtle" onClick={() => createSemanticNode("stage", positionRightOf(["dataset"]))}>Stage</Button>
                <Button type="button" variant="subtle" onClick={() => createSemanticNode("llm_pairwise", positionRightOf(["dataset"], { x: 40, y: 560 }))}>Judge</Button>
                <Button type="button" variant="subtle" onClick={() => createSemanticNode("human_pairwise", positionRightOf(["dataset"], { x: 40, y: 560 }))}>Review</Button>
              </div>
            </div>
            <div
              className="h-[72vh] min-h-[680px]"
              onDragOver={(event) => {
                event.preventDefault();
                event.dataTransfer.dropEffect = "copy";
              }}
              onDrop={(event) => {
                event.preventDefault();
                const kind = event.dataTransfer.getData("application/x-semantic-node-kind") as "stage" | "llm_pairwise" | "human_pairwise";
                if (!kind) return;
                createSemanticNode(kind, screenToFlowPosition({ x: event.clientX, y: event.clientY }));
              }}
            >
              <ReactFlow
                nodes={semanticNodes}
                edges={edges}
                nodeTypes={nodeTypes}
                fitView
                fitViewOptions={{ padding: 0.36 }}
                onNodesChange={onNodesChange}
                onNodeClick={(_, node) => setSelectedId(node.id)}
                onConnect={connectSemanticNodes}
                onNodeDragStop={(_, node) => {
                  const nextLayout = { ...layout, [node.id]: { x: Math.round(node.position.x), y: Math.round(node.position.y) } };
                  setLocalLayout(nextLayout);
                  updateLayout.mutate(nextLayout);
                }}
              >
                <Background />
                <Controls />
              </ReactFlow>
            </div>
          </div>

          <aside className="flex flex-col border-t border-line bg-surface lg:h-[calc(72vh+57px)] lg:min-h-[737px] lg:overflow-y-auto lg:border-l lg:border-t-0">
            <Inspector spec={spec} selectedId={selectedId} onSelect={setSelectedId} onChange={saveGraphSpec} />
          </aside>
        </section>

        <details className="panel overflow-hidden">
          <summary className="flex h-[57px] shrink-0 cursor-pointer items-center gap-2 border-b border-line bg-surface-muted px-4 text-sm font-bold [&::-webkit-details-marker]:hidden">
            <Braces size={15} className="text-accent" />
            Spec JSON
          </summary>
          <div className="grid gap-3 p-4">
            <Textarea id="spec-textarea" className="h-[200px] resize-none font-mono text-xs" value={specText} onChange={(event) => setDraft(event.target.value)} />
            {validation ? <ValidationPanel result={validation} onJumpToPath={jumpToPath} /> : null}
            <div className="flex gap-2">
              <Button type="button" variant="subtle" onClick={() => { try { validate.mutate(specText); } catch (exc) { setValidation({ valid: false, errors: [{ code: "invalid_json", path: "$", message: String(exc) }], warnings: [] }); } }}>Validate</Button>
              <Button type="button" onClick={() => { try { saveSpec.mutate(specText); } catch (exc) { setValidation({ valid: false, errors: [{ code: "invalid_json", path: "$", message: String(exc) }], warnings: [] }); } }}>
                <Save size={15} />
                Save Spec
              </Button>
            </div>
          </div>
        </details>
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
              {data.latest_run ? (
                <Button type="button" variant="subtle" onClick={() => navigate(`/graph-runs/${data.latest_run?.id}`)}>Latest Run</Button>
              ) : null}
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

function SemanticNode({ data }: { data: { node: SemanticNodeDto; spec: GraphSpec; onSelect: (id: string) => void; onStageChange: (id: string, stage: StageSpec) => void; onCandidateChange: (stageId: string, id: string, candidate: CandidateSpec) => void; onEvaluatorChange: (id: string, evaluator: EvaluatorSpec) => void } }) {
  const Icon = data.node.kind === "dataset" ? Database : data.node.kind === "evaluator" ? Gavel : data.node.kind === "candidate" ? Bot : GitBranch;
  const stage = data.spec.stages?.find((item) => item.id === data.node.id);
  const candidateStage = data.spec.stages?.find((item) => item.candidates.some((candidate) => candidate.id === data.node.id));
  const candidate = candidateStage?.candidates.find((item) => item.id === data.node.id);
  const evaluator = data.spec.evaluators?.find((item) => item.id === data.node.id);
  return (
    <div className="relative min-w-[320px] max-w-[380px] rounded-lg border border-line bg-surface shadow-sm">
      <Handle type="target" position={Position.Left} className="!left-[-5px]" />
      <div className="semantic-node-drag-handle flex cursor-grab items-center gap-2 border-b border-line px-3 py-2 active:cursor-grabbing">
        <Icon size={15} className="text-accent" />
        <strong className="truncate text-sm">{data.node.title}</strong>
      </div>
      <div className="nodrag nowheel grid gap-2 p-3 text-xs text-muted">
        <span className="font-mono">{data.node.id}</span>
        <span>{data.node.kind}</span>
        {stage ? (
          <CanvasStageFields spec={data.spec} stage={stage} onChange={(next) => data.onStageChange(stage.id, next)} onOpen={() => data.onSelect(stage.id)} />
        ) : null}
        {candidate && candidateStage ? (
          <CanvasCandidateFields candidate={candidate} onChange={(next) => data.onCandidateChange(candidateStage.id, candidate.id, next)} onOpen={() => data.onSelect(candidate.id)} />
        ) : null}
        {evaluator ? (
          <CanvasEvaluatorFields spec={data.spec} evaluator={evaluator} onChange={(next) => data.onEvaluatorChange(evaluator.id, next)} onOpen={() => data.onSelect(evaluator.id)} />
        ) : null}
      </div>
      <Handle type="source" position={Position.Right} className="!right-[-5px]" />
    </div>
  );
}

function CanvasStageFields({ spec, stage, onChange, onOpen }: { spec: GraphSpec; stage: StageSpec; onChange: (stage: StageSpec) => void; onOpen: () => void }) {
  const addCandidate = () => {
    const id = uniqueId("candidate", allCandidateIds(spec));
    onChange({
      ...stage,
      candidates: [
        ...stage.candidates,
        {
          id,
          title: "New candidate",
          model: "",
          prompt_inline: "",
          prompt_path: null,
          params: { temperature: 0.2, retry_count: 2, reasoning_effort: null },
        },
      ],
    });
  };
  return (
    <div className="grid gap-2">
      <Input className="h-8 text-xs" value={stage.title || ""} onChange={(event) => onChange({ ...stage, title: event.target.value })} aria-label="Stage title" />
      <div className="flex items-center justify-between gap-2">
        <div className="text-[11px] font-bold uppercase text-muted">{stage.candidates.length} candidate{stage.candidates.length === 1 ? "" : "s"}</div>
        <Button type="button" variant="subtle" onClick={addCandidate}><Plus size={13} /> Candidate</Button>
      </div>
      {stage.candidates.length === 0 ? <p className="rounded-md border border-dashed border-line p-2 text-[11px] text-muted">No candidates yet. Add one here or in the inspector.</p> : null}
      <Button type="button" variant="subtle" onClick={onOpen}>Open Inspector</Button>
    </div>
  );
}

function CanvasCandidateFields({ candidate, onChange, onOpen }: { candidate: CandidateSpec; onChange: (candidate: CandidateSpec) => void; onOpen: () => void }) {
  return (
    <div className="grid gap-2">
      <Input className="h-8 text-xs" value={candidate.title || ""} onChange={(event) => onChange({ ...candidate, title: event.target.value })} aria-label={`${candidate.id} title`} placeholder="Candidate title" />
      <Input className="h-8 text-xs" value={candidate.model || ""} onChange={(event) => onChange({ ...candidate, model: event.target.value })} aria-label={`${candidate.id} model`} placeholder="model/provider" />
      <div className="grid grid-cols-2 gap-1">
        <Input className="h-8 text-xs" value={String(candidate.params?.temperature ?? 0)} onChange={(event) => onChange({ ...candidate, params: { ...(candidate.params || {}), temperature: Number(event.target.value) } })} aria-label={`${candidate.id} temperature`} placeholder="temp" />
        <Input className="h-8 text-xs" value={candidate.params?.reasoning_effort || ""} onChange={(event) => onChange({ ...candidate, params: { ...(candidate.params || {}), reasoning_effort: event.target.value || null } })} aria-label={`${candidate.id} reasoning`} placeholder="reasoning" />
      </div>
      <Button type="button" variant="subtle" onClick={onOpen}>Open Inspector</Button>
    </div>
  );
}

function CanvasEvaluatorFields({ spec, evaluator, onChange, onOpen }: { spec: GraphSpec; evaluator: EvaluatorSpec; onChange: (evaluator: EvaluatorSpec) => void; onOpen: () => void }) {
  return (
    <div className="grid gap-2">
      <Input className="h-8 text-xs" value={evaluator.title || ""} onChange={(event) => onChange({ ...evaluator, title: event.target.value })} aria-label="Evaluator title" />
      <Select className="h-8 text-xs" value={evaluator.target_stage || ""} onChange={(event) => onChange({ ...evaluator, target_stage: event.target.value })}>
        {spec.stages.map((stage) => <option key={stage.id} value={stage.id}>{stage.title || stage.id}</option>)}
      </Select>
      {evaluator.type === "llm_pairwise" ? <Input className="h-8 text-xs" value={evaluator.model || ""} onChange={(event) => onChange({ ...evaluator, model: event.target.value })} aria-label="Judge model" /> : <span className="font-mono">human_pairwise</span>}
      <div className="grid grid-cols-2 gap-1">
        <Input className="h-8 text-xs" value={String(evaluator.pairing?.sample_pct ?? 100)} onChange={(event) => onChange({ ...evaluator, pairing: { ...evaluator.pairing, sample_pct: Number(event.target.value) } })} aria-label="Sample percent" />
        <Select className="h-8 text-xs" value={String(Boolean(evaluator.pairing?.swap))} onChange={(event) => onChange({ ...evaluator, pairing: { ...evaluator.pairing, swap: event.target.value === "true" } })}>
          <option value="false">swap off</option>
          <option value="true">swap on</option>
        </Select>
      </div>
      <Button type="button" variant="subtle" onClick={onOpen}>Open Inspector</Button>
    </div>
  );
}

function GraphToolbar({ spec, layout, positionRightOf, onChange }: { spec: GraphSpec; layout: Record<string, { x: number; y: number }>; positionRightOf: (sourceIds: string[], fallback?: { x: number; y: number }) => { x: number; y: number }; onAdd: (kind: "stage" | "llm_pairwise" | "human_pairwise", position: { x: number; y: number }) => void; onChange: (spec: GraphSpec, layout?: Record<string, { x: number; y: number }>) => void }) {
  const addStage = () => {
    const id = uniqueId("stage", spec.stages.map((stage) => stage.id));
    const previousStage = spec.stages.at(-1);
    const sourceIds = previousStage ? (previousStage.candidates.length ? previousStage.candidates.map((candidate) => candidate.id) : [previousStage.id]) : ["dataset"];
    onChange({ ...spec, stages: [...spec.stages, newStage(id)] }, { ...layout, [id]: positionRightOf(sourceIds) });
  };
  const addEvaluator = (type: "llm_pairwise" | "human_pairwise") => {
    const id = uniqueId(type === "human_pairwise" ? "human_review" : "judge", spec.evaluators.map((item) => item.id));
    const targetStage = spec.stages.at(-1);
    const sourceIds = targetStage ? (targetStage.candidates.length ? targetStage.candidates.map((candidate) => candidate.id) : [targetStage.id]) : ["dataset"];
    onChange({ ...spec, evaluators: [...spec.evaluators, newEvaluator(id, type, targetStage?.id || "")] }, { ...layout, [id]: positionRightOf(sourceIds, { x: 40, y: 560 }) });
  };
  const palette = [
    { kind: "stage" as const, label: "Stage", action: addStage },
    { kind: "llm_pairwise" as const, label: "LLM Judge", action: () => addEvaluator("llm_pairwise") },
    { kind: "human_pairwise" as const, label: "Human Judge", action: () => addEvaluator("human_pairwise") },
  ];
  return (
    <section className="panel grid gap-3 p-4">
      <h2 className="text-sm font-bold">Edit Graph</h2>
      <div className="flex flex-wrap gap-2">
        {palette.map((item) => (
          <button
            key={item.kind}
            type="button"
            draggable
            className="inline-flex min-h-9 cursor-grab items-center justify-center gap-2 rounded-md border border-line bg-surface px-3 py-1.5 text-sm font-semibold text-ink transition hover:border-line-strong hover:bg-surface-raised active:cursor-grabbing"
            onClick={item.action}
            onDragStart={(event) => {
              event.dataTransfer.setData("application/x-semantic-node-kind", item.kind);
              event.dataTransfer.effectAllowed = "copy";
            }}
            title={`Drag ${item.label} onto the canvas, or click to add one`}
          >
            <Plus size={15} />
            {item.label}
          </button>
        ))}
      </div>
    </section>
  );
}

function InspectorHeader({ icon, title, action }: { icon: ReactNode; title: string; action?: ReactNode }) {
  return (
    <div className="sticky top-0 z-10 flex h-[57px] shrink-0 items-center justify-between gap-3 border-b border-line bg-surface-muted px-4">
      <div className="flex min-w-0 items-center gap-2">
        <span className="text-accent">{icon}</span>
        <h2 className="truncate text-sm font-bold">{title}</h2>
      </div>
      {action ? <div className="flex items-center gap-1">{action}</div> : null}
    </div>
  );
}

function Inspector({ spec, selectedId, onSelect, onChange }: { spec: GraphSpec; selectedId: string; onSelect: (id: string) => void; onChange: (spec: GraphSpec) => void }) {
  const stage = spec.stages.find((item) => item.id === selectedId);
  const candidateStage = spec.stages.find((item) => item.candidates.some((candidate) => candidate.id === selectedId));
  const candidate = candidateStage?.candidates.find((item) => item.id === selectedId);
  const evaluator = spec.evaluators.find((item) => item.id === selectedId);
  if (selectedId === "dataset") {
    return (
      <div className="flex flex-col">
        <InspectorHeader icon={<Database size={16} />} title="Dataset" />
        <div className="grid gap-4 p-4">
          <Field label="Provider"><Select value={spec.dataset.provider} onChange={(event) => onChange({ ...spec, dataset: { ...spec.dataset, provider: event.target.value as "markdown_folder" | "csv" } })}><option value="markdown_folder">Markdown folder</option><option value="csv">CSV</option></Select></Field>
          <Field label="Path"><Input value={String(spec.dataset.config.path || "")} onChange={(event) => onChange({ ...spec, dataset: { ...spec.dataset, config: { ...spec.dataset.config, path: event.target.value } } })} /></Field>
        </div>
      </div>
    );
  }
  if (stage) return <StageInspector spec={spec} stage={stage} onSelect={onSelect} onChange={onChange} />;
  if (candidate && candidateStage) return <CandidateInspector spec={spec} stage={candidateStage} candidate={candidate} onSelect={onSelect} onChange={onChange} />;
  if (evaluator) return <EvaluatorInspector spec={spec} evaluator={evaluator} onSelect={onSelect} onChange={onChange} />;
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-3 p-6 text-center text-sm text-muted">
      <Database size={24} className="text-line-strong" />
      <p>Select a node to edit its properties.</p>
    </div>
  );
}

function StageInspector({ spec, stage, onSelect, onChange }: { spec: GraphSpec; stage: StageSpec; onSelect: (id: string) => void; onChange: (spec: GraphSpec) => void }) {
  const updateStage = (next: StageSpec) => onChange({ ...spec, stages: spec.stages.map((item) => item.id === stage.id ? next : item) });
  const deleteStage = () => {
    const nextStages = spec.stages.filter((item) => item.id !== stage.id);
    const fallback = nextStages.at(-1)?.id || "";
    onChange({ ...spec, stages: nextStages, evaluators: spec.evaluators.map((item) => item.target_stage === stage.id ? { ...item, target_stage: fallback } : item) });
    onSelect("dataset");
  };
  const addCandidate = () => {
    const id = uniqueId("candidate", allCandidateIds(spec));
    updateStage({ ...stage, candidates: [...stage.candidates, { id, title: "New candidate", model: "", prompt_inline: "", prompt_path: null, params: { temperature: 0.2, retry_count: 2, reasoning_effort: null } }] });
  };
  return (
    <div className="flex flex-col">
      <InspectorHeader
        icon={<GitBranch size={16} />}
        title={stage.title || stage.id}
        action={<Button type="button" variant="danger" onClick={deleteStage}><Trash2 size={14} /></Button>}
      />
      <div className="grid gap-4 p-4">
        <Field label="Title"><Input value={stage.title || ""} onChange={(event) => updateStage({ ...stage, title: event.target.value })} /></Field>
        <Field label="Upstream output"><Select value={stage.upstream_output || "raw"} onChange={(event) => updateStage({ ...stage, upstream_output: event.target.value as "raw" | "json" })}><option value="raw">Raw</option><option value="json">JSON</option></Select></Field>
        <div className="border-t border-line pt-4">
          <div className="mb-3 flex items-center justify-between">
            <h3 className="text-xs font-bold uppercase text-muted">Candidates</h3>
            <Button type="button" variant="subtle" onClick={addCandidate}><Plus size={14} /> Candidate</Button>
          </div>
          <div className="grid gap-3">
            {stage.candidates.map((candidate) => (
              <CandidateEditor
                key={candidate.id}
                candidate={candidate}
                onChange={(next) => updateStage({ ...stage, candidates: stage.candidates.map((item) => item.id === candidate.id ? next : item) })}
                onDelete={() => updateStage({ ...stage, candidates: stage.candidates.filter((item) => item.id !== candidate.id) })}
              />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function CandidateEditor({ candidate, onChange, onDelete, showHeader = true }: { candidate: CandidateSpec; onChange: (candidate: CandidateSpec) => void; onDelete: () => void; showHeader?: boolean }) {
  return (
    <article className="grid gap-2 rounded-md border border-line bg-surface-muted p-3">
      {showHeader ? (
        <div className="flex items-center justify-between gap-2">
          <strong className="text-sm">{candidate.title || candidate.id}</strong>
          <Button type="button" variant="danger" onClick={onDelete}><Trash2 size={14} /></Button>
        </div>
      ) : null}
      <Field label="Title"><Input value={candidate.title || ""} onChange={(event) => onChange({ ...candidate, title: event.target.value })} /></Field>
      <Field label="Model"><Input value={candidate.model || ""} onChange={(event) => onChange({ ...candidate, model: event.target.value })} /></Field>
      <div className="grid grid-cols-2 gap-2">
        <Field label="Temperature"><Input value={String(candidate.params?.temperature ?? 0)} onChange={(event) => onChange({ ...candidate, params: { ...candidate.params, temperature: Number(event.target.value) } })} /></Field>
        <Field label="Reasoning"><Input value={candidate.params?.reasoning_effort || ""} onChange={(event) => onChange({ ...candidate, params: { ...candidate.params, reasoning_effort: event.target.value || null } })} /></Field>
      </div>
      <Field label="Prompt"><Textarea className="h-32 font-mono text-xs" value={candidate.prompt_inline || ""} onChange={(event) => onChange({ ...candidate, prompt_inline: event.target.value, prompt_path: null })} /></Field>
    </article>
  );
}

function CandidateInspector({ spec, stage, candidate, onSelect, onChange }: { spec: GraphSpec; stage: StageSpec; candidate: CandidateSpec; onSelect: (id: string) => void; onChange: (spec: GraphSpec) => void }) {
  const updateCandidate = (next: CandidateSpec) => {
    onChange({
      ...spec,
      stages: spec.stages.map((item) => item.id === stage.id ? { ...item, candidates: item.candidates.map((existing) => existing.id === candidate.id ? next : existing) } : item),
    });
  };
  const deleteCandidate = () => {
    onChange({
      ...spec,
      stages: spec.stages.map((item) => item.id === stage.id ? { ...item, candidates: item.candidates.filter((existing) => existing.id !== candidate.id) } : item),
    });
    onSelect(stage.id);
  };
  return (
    <div className="flex flex-col">
      <InspectorHeader
        icon={<Bot size={16} />}
        title={candidate.title || candidate.id}
        action={<Button type="button" variant="danger" onClick={deleteCandidate}><Trash2 size={14} /></Button>}
      />
      <div className="grid gap-4 p-4">
        <p className="text-xs text-muted">Stage: {stage.title || stage.id}</p>
        <CandidateEditor candidate={candidate} onChange={updateCandidate} onDelete={deleteCandidate} showHeader={false} />
      </div>
    </div>
  );
}

function EvaluatorInspector({ spec, evaluator, onSelect, onChange }: { spec: GraphSpec; evaluator: EvaluatorSpec; onSelect: (id: string) => void; onChange: (spec: GraphSpec) => void }) {
  const updateEvaluator = (next: EvaluatorSpec) => onChange({ ...spec, evaluators: spec.evaluators.map((item) => item.id === evaluator.id ? next : item) });
  const deleteEvaluator = () => {
    onChange({ ...spec, evaluators: spec.evaluators.filter((item) => item.id !== evaluator.id) });
    onSelect("dataset");
  };
  return (
    <div className="flex flex-col">
      <InspectorHeader
        icon={<Gavel size={16} />}
        title={evaluator.title || evaluator.id}
        action={<Button type="button" variant="danger" onClick={deleteEvaluator}><Trash2 size={14} /></Button>}
      />
      <div className="grid gap-4 p-4">
        <Field label="Title"><Input value={evaluator.title || ""} onChange={(event) => updateEvaluator({ ...evaluator, title: event.target.value })} /></Field>
        <Field label="Target stage"><Select value={evaluator.target_stage || ""} onChange={(event) => updateEvaluator({ ...evaluator, target_stage: event.target.value })}>{spec.stages.map((stage) => <option key={stage.id} value={stage.id}>{stage.title || stage.id}</option>)}</Select></Field>
        <Field label="Type"><Select value={evaluator.type} onChange={(event) => updateEvaluator({ ...evaluator, type: event.target.value as "llm_pairwise" | "human_pairwise" })}><option value="llm_pairwise">LLM pairwise</option><option value="human_pairwise">Human pairwise</option></Select></Field>
        {evaluator.type === "llm_pairwise" ? (
          <>
            <Field label="Judge model"><Input value={evaluator.model || ""} onChange={(event) => updateEvaluator({ ...evaluator, model: event.target.value })} /></Field>
            <Field label="Judge prompt"><Textarea className="h-32 font-mono text-xs" value={evaluator.prompt_inline || ""} onChange={(event) => updateEvaluator({ ...evaluator, prompt_inline: event.target.value, prompt_path: null })} /></Field>
          </>
        ) : null}
        <div className="grid grid-cols-2 gap-2">
          <Field label="Sample %"><Input value={String(evaluator.pairing?.sample_pct ?? 100)} onChange={(event) => updateEvaluator({ ...evaluator, pairing: { ...evaluator.pairing, sample_pct: Number(event.target.value) } })} /></Field>
          <Field label="Swap"><Select value={String(Boolean(evaluator.pairing?.swap))} onChange={(event) => updateEvaluator({ ...evaluator, pairing: { ...evaluator.pairing, swap: event.target.value === "true" } })}><option value="false">Off</option><option value="true">On</option></Select></Field>
        </div>
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return <label className="grid gap-1 text-xs font-bold text-ink-soft">{label}{children}</label>;
}

function uniqueId(prefix: string, existing: string[]) {
  let index = existing.length + 1;
  let candidate = `${prefix}_${index}`;
  while (existing.includes(candidate)) {
    index += 1;
    candidate = `${prefix}_${index}`;
  }
  return candidate;
}

function allCandidateIds(spec: GraphSpec) {
  return spec.stages.flatMap((stage) => stage.candidates.map((candidate) => candidate.id));
}

function newStage(id: string): StageSpec {
  return {
    id,
    title: "New stage",
    fanout: "matrix",
    upstream_output: "raw",
    candidates: [],
  };
}

function newEvaluator(id: string, type: "llm_pairwise" | "human_pairwise", targetStage: string): EvaluatorSpec {
  return {
    id,
    title: type === "human_pairwise" ? "Human review" : "LLM judge",
    type,
    target_stage: targetStage,
    model: type === "human_pairwise" ? "" : "google/gemini-3-flash-preview",
    prompt_inline: type === "human_pairwise" ? null : "## Output A\n{{ output_a }}\n\n## Output B\n{{ output_b }}\n\nReturn JSON with `reasoning` and `winner` as A, B, or TIE.",
    prompt_path: null,
    pairing: { sample_pct: 100, swap: false, seed: null },
    output: { winner_key: "winner", reasoning_key: "reasoning" },
    params: { temperature: 0, retry_count: 2, reasoning_effort: null },
  };
}

function planStats(plan: GraphPlanDto) {
  return [
    ["Items", plan.transcript_count],
    ["Stages", plan.stage_count],
    ["Candidates", plan.candidate_count],
    ["Evaluators", plan.evaluator_count],
    ["Generation calls", plan.generation_calls],
    ["Pairs", plan.pair_count],
    ["Judge calls", plan.judge_calls],
    ["Human reviews", plan.human_review_count],
  ] as const;
}

function PlanPanel({ plan }: { plan: GraphPlanDto }) {
  const stats = [
    ["Items", plan.transcript_count],
    ["Stages", plan.stage_count],
    ["Candidates", plan.candidate_count],
    ["Evaluators", plan.evaluator_count],
    ["Generation calls", plan.generation_calls],
    ["Pairs", plan.pair_count],
    ["Judge calls", plan.judge_calls],
    ["Human reviews", plan.human_review_count],
  ];
  return (
    <section className="panel grid gap-4 p-4">
      <h2 className="text-sm font-bold">Execution Plan</h2>
      <div className="grid grid-cols-2 gap-2">
        {stats.map(([label, value]) => (
          <div key={label} className="rounded-md border border-line bg-surface-muted p-3">
            <div className="text-xs text-muted">{label}</div>
            <div className="text-lg font-extrabold">{Number(value).toLocaleString()}</div>
          </div>
        ))}
      </div>
      {plan.warnings.map((warning) => <p key={warning} className="rounded-md border border-warning/30 bg-warning-soft p-2 text-xs text-warning"><AlertTriangle size={13} className="mr-1 inline" />{warning}</p>)}
    </section>
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
