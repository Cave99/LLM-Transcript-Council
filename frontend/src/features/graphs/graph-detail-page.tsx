import { useCallback, useEffect, useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import ReactFlow, { Background, Controls, type Connection, type Edge, type Node, ReactFlowProvider, useEdgesState, useNodesState, useReactFlow } from "reactflow";
import { Clock, Database, FileText, Gavel, Maximize2, MessageSquare, Minimize2, Play, Settings } from "lucide-react";
import { client } from "../../api/client";
import { queryClient } from "../../api/queries";
import type { GraphNodeDto, GraphPlanDto, GraphRunSummary, NodeKind } from "../../api/types";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { StatusPill } from "../../components/status-pill";
import { EmptyState } from "../../components/empty-state";
import { confirmDanger } from "../../components/confirm-dialog";
import { GraphNodeCard } from "../graph-editor/graph-node";

const nodeTypes = { graphNode: GraphNodeCard };

const palette: { kind: NodeKind; label: string; icon: typeof Database }[] = [
  { kind: "dataset", label: "Dataset", icon: Database },
  { kind: "constant", label: "Constant", icon: FileText },
  { kind: "prompt", label: "Prompt", icon: MessageSquare },
  { kind: "model", label: "Model", icon: Settings },
  { kind: "judge", label: "Judge", icon: Gavel }
];

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
  const [workspaceFullscreen, setWorkspaceFullscreen] = useState(false);
  const { data, isLoading, error } = useQuery({ queryKey: ["graph", graphId], queryFn: () => client.graph(graphId), enabled: Number.isFinite(graphId) });

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["graph", graphId] });
  const createNode = useMutation({ mutationFn: ({ kind, x, y }: { kind: NodeKind; x?: number; y?: number }) => client.createNode(graphId, kind, x, y), onSuccess: invalidate });
  const updateNode = useMutation({ mutationFn: ({ node, title, body, config }: { node: GraphNodeDto; title: string; body: string; config: Record<string, unknown> }) => client.updateNode(node.id, title, body, config), onSuccess: invalidate });
  const deleteNode = useMutation({ mutationFn: (node: GraphNodeDto) => client.deleteNode(node.id), onSuccess: invalidate });
  const updatePosition = useMutation({ mutationFn: ({ node, x, y }: { node: GraphNodeDto; x: number; y: number }) => client.updateNodePosition(node.id, Math.round(x), Math.round(y), node.width, node.height), onSuccess: invalidate });
  const createEdge = useMutation({ mutationFn: (connection: Connection) => client.createEdge(graphId, Number(connection.source), connection.sourceHandle || "output", Number(connection.target), connection.targetHandle || "input"), onSuccess: invalidate });
  const deleteEdge = useMutation({ mutationFn: (edge: Edge) => client.deleteEdge(Number(edge.id)), onSuccess: invalidate });
  const renameGraph = useMutation({ mutationFn: (name: string) => client.renameGraph(graphId, name), onSuccess: invalidate });
  const launch = useMutation({
    mutationFn: (mode: "test" | "full") => client.launchGraph(graphId, mode, 5),
    onSuccess: (run) => navigate(`/graph-runs/${run.id}`)
  });
  const saveNode = useCallback(
    (target: GraphNodeDto, title: string, body: string, config: Record<string, unknown>) => updateNode.mutate({ node: target, title, body, config }),
    [updateNode.mutate]
  );
  const removeNode = useCallback(
    (target: GraphNodeDto) => {
      if (confirmDanger(`Delete node "${target.title}"?`)) deleteNode.mutate(target);
    },
    [deleteNode.mutate]
  );

  const graphNodes: Node[] = useMemo(() => (data?.nodes || []).map((node) => ({
    id: String(node.id),
    type: "graphNode",
    position: { x: node.x, y: node.y },
    data: {
      node,
      onSave: saveNode,
      onDelete: removeNode,
    }
  })), [data?.nodes, removeNode, saveNode]);

  const graphEdges: Edge[] = useMemo(() => (data?.edges || []).map((edge) => ({
    id: String(edge.id),
    source: String(edge.from_node_id),
    target: String(edge.to_node_id),
    sourceHandle: edge.from_socket,
    targetHandle: edge.to_socket
  })), [data?.edges]);

  const [nodes, setNodes, onNodesChange] = useNodesState(graphNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(graphEdges);

  useEffect(() => {
    setNodes((current) => sameNodeLayout(current, graphNodes) ? current : graphNodes);
  }, [graphNodes, setNodes]);

  useEffect(() => {
    setEdges((current) => sameEdgeLayout(current, graphEdges) ? current : graphEdges);
  }, [graphEdges, setEdges]);

  if (isLoading) return <p className="text-sm text-muted">Loading graph...</p>;
  if (error || !data) return <p className="text-sm text-danger">{String(error || "Graph not found")}</p>;

  return (
    <div className="grid gap-6">
      <section className="flex items-end justify-between gap-6 border-b border-line pb-6">
        <div className="grid gap-3">
          <div className="flex items-center gap-3">
            <h1 className="text-3xl font-extrabold">{data.graph.name}</h1>
            <StatusPill status={data.graph.status} />
          </div>
          <form className="flex max-w-md gap-2" onSubmit={(event) => {
            event.preventDefault();
            const name = String(new FormData(event.currentTarget).get("name") || "").trim();
            if (name) renameGraph.mutate(name);
          }}>
            <Input name="name" defaultValue={data.graph.name} />
            <Button variant="subtle">Rename</Button>
          </form>
        </div>
        <div className="flex gap-2">
          {data.latest_run ? <Button type="button" variant="subtle" onClick={() => navigate(`/graph-runs/${data.latest_run?.id}`)}>Latest Run</Button> : null}
          <Button type="button" variant="subtle" onClick={() => launch.mutate("test")}>Test Run</Button>
          <Button type="button" onClick={() => launch.mutate("full")}><Play size={16} /> Launch</Button>
        </div>
      </section>

      <section className="grid grid-cols-[1fr_320px] gap-4">
        <div className={workspaceFullscreen ? "fixed inset-4 z-50 grid grid-rows-[auto_1fr] overflow-hidden rounded-lg border border-line bg-surface shadow-xl" : "panel grid grid-rows-[auto_1fr] overflow-hidden"}>
          <div className="flex items-center justify-between gap-3 border-b border-line bg-surface-muted p-3">
            <div className="flex items-center gap-2">
            {palette.map((item) => {
              const Icon = item.icon;
              return (
                <button
                  key={item.kind}
                  type="button"
                  draggable
                  className="inline-flex min-h-9 cursor-grab items-center justify-center gap-2 rounded-md border border-line bg-surface px-3 py-1.5 text-sm font-semibold text-ink transition hover:border-line-strong hover:bg-surface-raised active:cursor-grabbing"
                  onClick={() => createNode.mutate({ kind: item.kind, x: 80 + data.nodes.length * 24, y: 80 + data.nodes.length * 18 })}
                  onDragStart={(event) => {
                    event.dataTransfer.setData("application/x-graph-node-kind", item.kind);
                    event.dataTransfer.effectAllowed = "copy";
                  }}
                  title={`Drag ${item.label} onto the canvas, or click to add one`}
                >
                  <Icon size={15} />
                  {item.label}
                </button>
              );
            })}
            </div>
            <Button type="button" variant="subtle" onClick={() => setWorkspaceFullscreen((value) => !value)}>
              {workspaceFullscreen ? <Minimize2 size={15} /> : <Maximize2 size={15} />}
              {workspaceFullscreen ? "Exit Fullscreen" : "Fullscreen Graph"}
            </Button>
          </div>
          <div
            className={workspaceFullscreen ? "h-full min-h-0" : "h-[640px]"}
            onDragOver={(event) => {
              event.preventDefault();
              event.dataTransfer.dropEffect = "copy";
            }}
            onDrop={(event) => {
              event.preventDefault();
              const kind = event.dataTransfer.getData("application/x-graph-node-kind") as NodeKind;
              if (!kind) return;
              const position = screenToFlowPosition({ x: event.clientX, y: event.clientY });
              createNode.mutate({ kind, x: Math.round(position.x), y: Math.round(position.y) });
            }}
          >
            <ReactFlow
              nodes={nodes}
              edges={edges}
              nodeTypes={nodeTypes}
              onNodesChange={onNodesChange}
              onEdgesChange={onEdgesChange}
              onConnect={(connection) => createEdge.mutate(connection)}
              onNodeDragStop={(_, node) => {
                const original = data.nodes.find((item) => String(item.id) === node.id);
                if (original) updatePosition.mutate({ node: original, x: node.position.x, y: node.position.y });
              }}
              onEdgesDelete={(removed) => removed.forEach((edge) => deleteEdge.mutate(edge))}
              fitView
            >
              <Background />
              <Controls />
              {!nodes.length ? (
                <div className="pointer-events-none absolute left-5 top-5 z-10">
                  <EmptyState title="No nodes yet" body="Drag a node from the library onto the canvas to draft an evaluation graph." />
                </div>
              ) : null}
            </ReactFlow>
          </div>
        </div>

        <aside className="grid content-start gap-4">
          <PlanPanel plan={data.plan} />
          <RunHistory runs={data.graph_runs} onOpen={(id) => navigate(`/graph-runs/${id}`)} />
          <div className="panel grid gap-3 p-4">
            <h2 className="text-sm font-bold">Project</h2>
            <Link className="text-sm text-accent hover:text-accent-hover" to={`/projects/${data.graph.project_id}`}>Back to project</Link>
          </div>
        </aside>
      </section>
    </div>
  );
}

function sameNodeLayout(current: Node[], next: Node[]) {
  if (current.length !== next.length) return false;
  const currentById = new Map(current.map((node) => [node.id, node]));
  return next.every((node) => {
    const existing = currentById.get(node.id);
    if (!existing) return false;
    return (
      existing.position.x === node.position.x &&
      existing.position.y === node.position.y &&
      existing.type === node.type &&
      existing.data?.node?.updated_at === node.data?.node?.updated_at
    );
  });
}

function sameEdgeLayout(current: Edge[], next: Edge[]) {
  if (current.length !== next.length) return false;
  const currentById = new Map(current.map((edge) => [edge.id, edge]));
  return next.every((edge) => {
    const existing = currentById.get(edge.id);
    if (!existing) return false;
    return (
      existing.source === edge.source &&
      existing.target === edge.target &&
      existing.sourceHandle === edge.sourceHandle &&
      existing.targetHandle === edge.targetHandle
    );
  });
}

function RunHistory({ runs, onOpen }: { runs: GraphRunSummary[]; onOpen: (id: number) => void }) {
  return (
    <div className="panel grid gap-3 p-4">
      <div className="flex items-center gap-2">
        <Clock size={15} className="text-accent" />
        <h2 className="text-sm font-bold">Previous Runs</h2>
      </div>
      {runs.length ? (
        <div className="grid gap-2">
          {runs.map((run) => (
            <button key={run.id} type="button" className="grid gap-1 rounded-md border border-line bg-surface px-3 py-2 text-left transition hover:border-line-strong hover:bg-surface-raised" onClick={() => onOpen(run.id)}>
              <span className="flex items-center justify-between gap-2">
                <span className="truncate text-sm font-semibold">{run.name}</span>
                <StatusPill status={run.status} />
              </span>
              <span className="text-xs text-muted">{run.sample_size === 1 ? "test run" : "full run"} · {new Date(run.created_at).toLocaleString()}</span>
            </button>
          ))}
        </div>
      ) : (
        <p className="text-sm text-muted">No runs yet.</p>
      )}
    </div>
  );
}

function PlanPanel({ plan }: { plan: GraphPlanDto }) {
  const stats = [
    ["Transcripts", plan.transcript_count],
    ["Prompt stages", plan.prompt_stage_count],
    ["Generator models", plan.generator_model_count],
    ["Judge models", plan.judge_model_count],
    ["Generation calls", plan.generation_calls],
    ["Matches", plan.match_count],
    ["Judge calls", plan.judge_calls]
  ];
  return (
    <div className="panel grid gap-4 p-4">
      <h2 className="text-sm font-bold">Execution Plan</h2>
      <div className="grid grid-cols-2 gap-2">
        {stats.map(([label, value]) => (
          <div key={label} className="rounded-md border border-line bg-surface-muted p-3">
            <div className="text-xs text-muted">{label}</div>
            <div className="text-lg font-extrabold">{Number(value).toLocaleString()}</div>
          </div>
        ))}
      </div>
      {plan.warnings.length ? (
        <div className="grid gap-2">
          {plan.warnings.map((warning) => <p key={warning} className="rounded-md border border-warning/30 bg-warning-soft p-2 text-xs text-warning">{warning}</p>)}
        </div>
      ) : <p className="text-sm text-muted">No launch warnings.</p>}
    </div>
  );
}
