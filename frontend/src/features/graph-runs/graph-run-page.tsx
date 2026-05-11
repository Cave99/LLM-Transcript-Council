import { useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Link, useParams, useSearchParams } from "react-router-dom";
import ReactFlow, { Background, Controls, type Edge, type Node, Position, Handle } from "reactflow";
import { Database, FileText, Gavel, MessageSquare, RotateCcw, Settings, Square, StepForward } from "lucide-react";
import { client } from "../../api/client";
import { queryClient } from "../../api/queries";
import type { GraphInvocationDto, GraphNodeDto, GraphProgress, LeaderboardView } from "../../api/types";
import { Button } from "../../components/ui/button";
import { Progress } from "../../components/ui/progress";
import { Table } from "../../components/ui/table";
import { StatusPill } from "../../components/status-pill";
import { DataTable } from "../../components/data-table";

const runNodeTypes = { runPreview: RunPreviewNode };

export function GraphRunPage() {
  const runId = Number(useParams().graphRunId);
  const [params, setParams] = useSearchParams();
  const view = ((params.get("leaderboard_view") || "aggregate") as LeaderboardView);
  const { data, isLoading, error } = useQuery({
    queryKey: ["graph-run", runId, view],
    queryFn: () => client.graphRun(runId, view),
    enabled: Number.isFinite(runId),
    refetchInterval: (query) => query.state.data?.run.status === "running" ? 5000 : false
  });
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["graph-run", runId] });
  const stop = useMutation({ mutationFn: () => client.stopRun(runId), onSuccess: invalidate });
  const cont = useMutation({ mutationFn: () => client.continueRun(runId), onSuccess: invalidate });
  const retry = useMutation({ mutationFn: () => client.retryFailures(runId), onSuccess: invalidate });
  const summary = useMutation({ mutationFn: ({ judge, entity }: { judge?: number | null; entity?: string }) => client.judgeSummary(runId, view, judge, entity || ""), onSuccess: invalidate });

  if (isLoading) return <p className="text-sm text-muted">Loading run...</p>;
  if (error || !data) return <p className="text-sm text-danger">{String(error || "Run not found")}</p>;

  const percent = data.progress.total ? (data.progress.complete / data.progress.total) * 100 : 0;
  return (
    <div className="grid gap-7">
      <section className="flex items-end justify-between gap-6 border-b border-line pb-6">
        <div className="grid gap-2">
          <div className="flex items-center gap-3">
            <h1 className="text-3xl font-extrabold">{data.run.name}</h1>
            <StatusPill status={data.run.status} />
          </div>
          <Link className="text-sm text-accent hover:text-accent-hover" to={`/graphs/${data.graph.id}`}>{data.graph.name}</Link>
        </div>
        <div className="flex gap-2">
          {data.run.status === "running" ? <Button variant="subtle" onClick={() => stop.mutate()}><Square size={15} /> Stop</Button> : null}
          {["paused", "pending", "failed"].includes(data.run.status) ? <Button onClick={() => cont.mutate()}><StepForward size={15} /> Continue</Button> : null}
          {data.progress.failed ? <Button variant="subtle" onClick={() => retry.mutate()}><RotateCcw size={15} /> Retry Failures</Button> : null}
        </div>
      </section>

      <section className="panel grid gap-3 p-4">
        <div className="flex items-center justify-between text-sm">
          <strong>Progress</strong>
          <span className="text-muted">{data.progress.complete}/{data.progress.total} complete · {data.progress.failed} failed</span>
        </div>
        <Progress value={percent} />
        <div className="flex flex-wrap gap-2 text-xs text-muted">
          <span>Pending {data.progress.pending}</span>
          <span>Running {data.progress.running}</span>
          <span>Complete {data.progress.complete}</span>
          <span>Failed {data.progress.failed}</span>
        </div>
        {data.diagnostics.map((diagnostic) => <p key={diagnostic.message} className="text-sm text-muted">{diagnostic.message}</p>)}
      </section>

      <RunGraphPreview nodes={data.nodes} edges={data.edges} nodeProgress={data.node_progress} />

      <section className="panel grid gap-4 p-4">
        <div className="flex items-center justify-between gap-3">
          <h2 className="text-sm font-bold">Leaderboards</h2>
          <div className="flex gap-2">
            {(["aggregate", "overall", "chain"] as LeaderboardView[]).map((option) => (
              <Button key={option} type="button" variant={view === option ? "default" : "subtle"} onClick={() => setParams({ leaderboard_view: option })}>
                {option === "aggregate" ? "Aggregated for step" : option === "overall" ? "Aggregated across steps" : "Show chain"}
              </Button>
            ))}
          </div>
        </div>
        {data.leaderboards.map((group) => (
          <div key={`${group.title}-${group.judge_prompt_node_id ?? "overall"}`} className="grid gap-3">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-bold">{group.title}</h3>
              <Button type="button" variant="subtle" onClick={() => summary.mutate({ judge: group.judge_prompt_node_id })}>Summarize</Button>
            </div>
            <DataTable>
              <Table>
                <thead className="border-b border-line bg-surface-muted text-xs text-muted">
                  <tr><th className="p-2">Rank</th><th className="p-2">Model</th><th className="p-2">ELO</th><th className="p-2">W-L-T</th><th className="p-2">Avg tokens</th></tr>
                </thead>
                <tbody>
                  {group.rows.map((row, index) => (
                    <tr key={row.entity_key} className="border-b border-line last:border-0">
                      <td className="p-2 text-muted">{index + 1}</td>
                      <td className="p-2 font-semibold">{row.label}</td>
                      <td className="p-2">{row.rating.toFixed(1)}</td>
                      <td className="p-2">{row.wins}-{row.losses}-{row.ties}</td>
                      <td className="p-2">{row.avg_tokens}</td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            </DataTable>
          </div>
        ))}
      </section>

      {data.analyses.length ? (
        <section className="panel grid gap-3 p-4">
          <h2 className="text-sm font-bold">Judge Summaries</h2>
          {data.analyses.map((analysis) => (
            <article key={analysis.id} className="rounded-md border border-line bg-surface-muted p-3">
              <h3 className="text-sm font-bold">{analysis.top_entity_label}</h3>
              <pre className="mt-2 font-sans text-sm leading-6 text-ink-soft">{analysis.summary}</pre>
            </article>
          ))}
        </section>
      ) : null}

      <OutputBrowser invocations={data.invocations} nodes={data.nodes} />
    </div>
  );
}

function RunGraphPreview({ nodes, edges, nodeProgress }: { nodes: GraphNodeDto[]; edges: { id: number; from_node_id: number; from_socket: string; to_node_id: number; to_socket: string }[]; nodeProgress: Record<number, GraphProgress> }) {
  const flowNodes: Node[] = useMemo(() => nodes.map((node) => ({
    id: String(node.id),
    type: "runPreview",
    position: { x: node.x, y: node.y },
    data: { node, progress: nodeProgress[node.id] },
    draggable: false,
    selectable: false,
    style: { width: 260 }
  })), [nodeProgress, nodes]);

  const flowEdges: Edge[] = useMemo(() => edges.map((edge) => ({
    id: String(edge.id),
    source: String(edge.from_node_id),
    target: String(edge.to_node_id),
    sourceHandle: edge.from_socket,
    targetHandle: edge.to_socket,
    animated: Boolean(nodeProgress[edge.from_node_id]?.running || nodeProgress[edge.to_node_id]?.running)
  })), [edges, nodeProgress]);

  return (
    <section className="panel overflow-hidden">
      <div className="flex items-center justify-between border-b border-line bg-surface-muted px-4 py-3">
        <h2 className="text-sm font-bold">Graph Preview</h2>
        <span className="text-xs text-muted">Per-node work updates with the run</span>
      </div>
      <div className="h-[420px]">
        <ReactFlow
          nodes={flowNodes}
          edges={flowEdges}
          nodeTypes={runNodeTypes}
          nodesDraggable={false}
          nodesConnectable={false}
          elementsSelectable={false}
          fitView
        >
          <Background />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>
    </section>
  );
}

function RunPreviewNode({ data }: { data: { node: GraphNodeDto; progress?: GraphProgress } }) {
  const node = data.node;
  const progress = data.progress || { total: 0, pending: 0, running: 0, complete: 0, failed: 0 };
  const Icon = previewIcons[node.kind as keyof typeof previewIcons] || FileText;
  const status = progress.failed ? "failed" : progress.running ? "running" : progress.total && progress.complete === progress.total ? "complete" : "pending";

  return (
    <div className="relative rounded-lg border border-line bg-surface shadow-sm">
      <div className="flex items-start justify-between gap-3 border-b border-line px-3 py-2">
        <div className="flex min-w-0 items-center gap-2">
          <Icon size={15} className="text-accent" />
          <div className="min-w-0">
            <strong className="block truncate text-sm">{node.title}</strong>
            <span className="block text-[10px] font-bold uppercase tracking-wide text-muted">{node.kind}</span>
          </div>
        </div>
        <span className={[
          "rounded-full border px-2 py-0.5 text-[11px] font-bold",
          status === "complete" ? "border-success/30 bg-success-soft text-success" : "",
          status === "running" ? "border-warning/30 bg-warning-soft text-warning" : "",
          status === "failed" ? "border-danger/30 bg-danger-soft text-danger" : "",
          status === "pending" ? "border-line bg-surface-muted text-muted" : ""
        ].join(" ")}>
          {progress.complete}/{progress.total}
        </span>
      </div>
      <div className="grid grid-cols-3 gap-1 p-3 text-center text-[11px] text-muted">
        <span>Pending {progress.pending}</span>
        <span>Running {progress.running}</span>
        <span>Failed {progress.failed}</span>
      </div>
      {node.input_sockets.map((socket, index) => (
        <Handle key={`in-${socket}`} type="target" id={socket} position={Position.Left} className="!left-[-5px]" style={{ top: 48 + index * 16 }} />
      ))}
      {node.output_sockets.map((socket, index) => (
        <Handle key={`out-${socket}`} type="source" id={socket} position={Position.Right} className="!right-[-5px]" style={{ top: 48 + index * 16 }} />
      ))}
    </div>
  );
}

const previewIcons = {
  dataset: Database,
  prompt: MessageSquare,
  constant: FileText,
  model: Settings,
  judge: Gavel
};

function OutputBrowser({ invocations, nodes }: { invocations: GraphInvocationDto[]; nodes: GraphNodeDto[] }) {
  const [openId, setOpenId] = useState<number | null>(null);
  const groups = useMemo(() => {
    const nodeById = new Map(nodes.map((node) => [node.id, node]));
    const map = new Map<string, Map<string, Map<string, GraphInvocationDto[]>>>();
    invocations.forEach((invocation) => {
      const node = nodeById.get(invocation.node_id);
      const role = node?.kind === "judge" ? "Judge outputs" : "Generator outputs";
      const promptTitle = invocation.node_title || "Unknown prompt";
      const modelTitle = invocation.model_title || "Unknown model";
      if (!map.has(role)) map.set(role, new Map());
      const promptMap = map.get(role)!;
      if (!promptMap.has(promptTitle)) promptMap.set(promptTitle, new Map());
      const modelMap = promptMap.get(promptTitle)!;
      modelMap.set(modelTitle, [...(modelMap.get(modelTitle) || []), invocation]);
    });
    return [...map.entries()];
  }, [invocations, nodes]);

  return (
    <section className="grid gap-4">
      <h2 className="text-sm font-bold">Model Outputs</h2>
      {groups.map(([role, promptGroups]) => (
        <div key={role} className="panel grid gap-4 p-4">
          <h3 className="text-sm font-bold">{role}</h3>
          {[...promptGroups.entries()].map(([promptTitle, modelGroups]) => (
            <div key={promptTitle} className="grid gap-3 rounded-lg border border-line bg-surface-muted/50 p-3">
              <h4 className="text-sm font-bold">{promptTitle}</h4>
              {[...modelGroups.entries()].map(([modelTitle, rows]) => (
                <div key={modelTitle} className="grid gap-2 rounded-md border border-line bg-surface p-3">
                  <div className="flex items-center justify-between gap-3">
                    <h5 className="text-sm font-semibold">{modelTitle}</h5>
                    <span className="text-xs text-muted">{rows.length} call{rows.length === 1 ? "" : "s"}</span>
                  </div>
                  {rows.map((invocation) => (
                    <InvocationCard key={invocation.id} invocation={invocation} open={openId === invocation.id} onToggle={() => setOpenId(openId === invocation.id ? null : invocation.id)} />
                  ))}
                </div>
              ))}
            </div>
          ))}
        </div>
      ))}
    </section>
  );
}

function InvocationCard({ invocation, open, onToggle }: { invocation: GraphInvocationDto; open: boolean; onToggle: () => void }) {
  return (
    <article className="rounded-md border border-line bg-surface p-3">
      <button className="flex w-full items-center justify-between text-left" onClick={onToggle}>
        <span className="font-semibold">{invocation.item_key}</span>
        <StatusPill status={invocation.status} />
      </button>
      {open ? (
        <div className="mt-3 grid gap-3 text-sm">
          {invocation.error ? <p className="text-danger">{invocation.error}</p> : null}
          <pre className="rounded-md bg-surface-muted p-3">{invocation.output_json || invocation.output_raw || "No output"}</pre>
          <details>
            <summary className="cursor-pointer text-muted">Rendered prompt</summary>
            <pre className="mt-2 rounded-md bg-surface-muted p-3">{invocation.rendered_prompt}</pre>
          </details>
        </div>
      ) : null}
    </article>
  );
}
