import { useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import ReactFlow, { Background, Controls, type Connection, type Edge, type Node, ReactFlowProvider } from "reactflow";
import { Database, FileText, Gavel, MessageSquare, Play, Plus, Settings } from "lucide-react";
import { client } from "../../api/client";
import { queryClient } from "../../api/queries";
import type { GraphNodeDto, GraphPlanDto, NodeKind } from "../../api/types";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { StatusPill } from "../../components/status-pill";
import { EmptyState } from "../../components/empty-state";
import { confirmDanger } from "../../components/confirm-dialog";
import { GraphNodeCard } from "../graph-editor/graph-node";
import { NodeEditor } from "../graph-editor/node-editor";

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
  const graphId = Number(useParams().graphId);
  const [selectedNode, setSelectedNode] = useState<GraphNodeDto | null>(null);
  const { data, isLoading, error } = useQuery({ queryKey: ["graph", graphId], queryFn: () => client.graph(graphId), enabled: Number.isFinite(graphId) });

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["graph", graphId] });
  const createNode = useMutation({ mutationFn: ({ kind, x, y }: { kind: NodeKind; x?: number; y?: number }) => client.createNode(graphId, kind, x, y), onSuccess: invalidate });
  const updateNode = useMutation({ mutationFn: ({ node, title, body, config }: { node: GraphNodeDto; title: string; body: string; config: Record<string, unknown> }) => client.updateNode(node.id, title, body, config), onSuccess: () => { setSelectedNode(null); invalidate(); } });
  const deleteNode = useMutation({ mutationFn: (node: GraphNodeDto) => client.deleteNode(node.id), onSuccess: () => { setSelectedNode(null); invalidate(); } });
  const updatePosition = useMutation({ mutationFn: ({ node, x, y }: { node: GraphNodeDto; x: number; y: number }) => client.updateNodePosition(node.id, Math.round(x), Math.round(y), node.width, node.height), onSuccess: invalidate });
  const createEdge = useMutation({ mutationFn: (connection: Connection) => client.createEdge(graphId, Number(connection.source), connection.sourceHandle || "output", Number(connection.target), connection.targetHandle || "input"), onSuccess: invalidate });
  const deleteEdge = useMutation({ mutationFn: (edge: Edge) => client.deleteEdge(Number(edge.id)), onSuccess: invalidate });
  const renameGraph = useMutation({ mutationFn: (name: string) => client.renameGraph(graphId, name), onSuccess: invalidate });
  const launch = useMutation({
    mutationFn: (mode: "test" | "full") => client.launchGraph(graphId, mode, 5),
    onSuccess: (run) => navigate(`/graph-runs/${run.id}`)
  });

  const nodes: Node[] = useMemo(() => (data?.nodes || []).map((node) => ({
    id: String(node.id),
    type: "graphNode",
    position: { x: node.x, y: node.y },
    data: { node, onEdit: setSelectedNode },
    style: { width: node.width }
  })), [data?.nodes]);

  const edges: Edge[] = useMemo(() => (data?.edges || []).map((edge) => ({
    id: String(edge.id),
    source: String(edge.from_node_id),
    target: String(edge.to_node_id),
    sourceHandle: edge.from_socket,
    targetHandle: edge.to_socket
  })), [data?.edges]);

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
        <div className="panel overflow-hidden">
          <div className="flex items-center gap-2 border-b border-line bg-surface-muted p-3">
            {palette.map((item) => {
              const Icon = item.icon;
              return (
                <Button key={item.kind} type="button" variant="subtle" onClick={() => createNode.mutate({ kind: item.kind, x: 80 + data.nodes.length * 24, y: 80 + data.nodes.length * 18 })}>
                  <Icon size={15} />
                  {item.label}
                </Button>
              );
            })}
          </div>
          <div className="h-[640px]">
            {nodes.length ? (
              <ReactFlow
                nodes={nodes}
                edges={edges}
                nodeTypes={nodeTypes}
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
              </ReactFlow>
            ) : (
              <div className="p-5"><EmptyState title="No nodes yet" body="Add a dataset, prompt, model, and judge node to draft an evaluation graph." /></div>
            )}
          </div>
        </div>

        <aside className="grid content-start gap-4">
          <PlanPanel plan={data.plan} />
          <div className="panel grid gap-3 p-4">
            <h2 className="text-sm font-bold">Project</h2>
            <Link className="text-sm text-accent hover:text-accent-hover" to={`/projects/${data.graph.project_id}`}>Back to project</Link>
          </div>
        </aside>
      </section>

      <NodeEditor
        node={selectedNode}
        onClose={() => setSelectedNode(null)}
        onSave={(node, title, body, config) => updateNode.mutate({ node, title, body, config })}
        onDelete={(node) => {
          if (confirmDanger(`Delete node "${node.title}"?`)) deleteNode.mutate(node);
        }}
      />
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
