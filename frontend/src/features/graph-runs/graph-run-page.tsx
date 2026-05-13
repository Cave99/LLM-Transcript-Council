import { useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import ReactFlow, { Background, Controls, Handle, Position, type Edge, type Node } from "reactflow";
import { ArrowLeft, Bot, Database, Gavel, GitBranch, RotateCcw, Square, StepForward } from "lucide-react";
import { client } from "../../api/client";
import { queryClient } from "../../api/queries";
import type { GraphInvocationDto, GraphPairDto, GraphRunDetail, SemanticNodeDto } from "../../api/types";
import { Button } from "../../components/ui/button";
import { Progress } from "../../components/ui/progress";
import { Table } from "../../components/ui/table";
import { StatusPill } from "../../components/status-pill";
import { DataTable } from "../../components/data-table";
import { Textarea } from "../../components/ui/textarea";
import { Input } from "../../components/ui/input";

const runNodeTypes = { semantic: RunNode };

export function GraphRunPage() {
  const runId = Number(useParams().graphRunId);
  const { data, isLoading, error } = useQuery({
    queryKey: ["graph-run", runId],
    queryFn: () => client.graphRun(runId, "aggregate"),
    enabled: Number.isFinite(runId),
    refetchInterval: (query) => query.state.data?.run.status === "running" ? 5000 : false
  });
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["graph-run", runId] });
  const stop = useMutation({ mutationFn: () => client.stopRun(runId), onSuccess: invalidate });
  const cont = useMutation({ mutationFn: () => client.continueRun(runId), onSuccess: invalidate });
  const retry = useMutation({ mutationFn: () => client.retryFailures(runId), onSuccess: invalidate });

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
          <Link
            className="inline-flex min-h-9 items-center justify-center gap-2 rounded-md border border-line bg-surface px-3 py-1.5 text-sm font-semibold transition hover:border-line-strong hover:bg-surface-muted focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-accent/20"
            to={`/graphs/${data.graph.id}`}
          >
            <ArrowLeft size={15} /> Back to Graph
          </Link>
          {data.run.status === "running" ? <Button variant="subtle" onClick={() => stop.mutate()}><Square size={15} /> Stop</Button> : null}
          {["paused", "pending", "failed"].includes(data.run.status) ? <Button onClick={() => cont.mutate()}><StepForward size={15} /> Continue</Button> : null}
          {data.progress.failed ? <Button variant="subtle" onClick={() => retry.mutate()}><RotateCcw size={15} /> Retry Failures</Button> : null}
        </div>
      </section>

      <RunGraphPreview data={data} />
      <LeaderboardsSection data={data} />
      <HumanEvalSection runId={runId} pairs={data.human_evals} onChanged={invalidate} />
      <OutputBrowser invocations={data.invocations} />
    </div>
  );
}

function RunGraphPreview({ data }: { data: GraphRunDetail }) {
  const nodes: Node[] = useMemo(() => data.nodes.map((node) => ({ id: node.id, type: "semantic", position: { x: node.x, y: node.y }, data: { node }, draggable: false })), [data.nodes]);
  const edges: Edge[] = useMemo(() => data.edges.map((edge) => ({ id: edge.id, source: edge.source, target: edge.target })), [data.edges]);
  return (
    <section className="panel overflow-hidden">
      <div className="flex items-center justify-between border-b border-line bg-surface-muted px-4 py-3">
        <h2 className="text-sm font-bold">Run Graph</h2>
        <span className="text-xs text-muted">Semantic spec preview</span>
      </div>
      <div className="h-[360px]">
        <ReactFlow nodes={nodes} edges={edges} nodeTypes={runNodeTypes} nodesDraggable={false} nodesConnectable={false} elementsSelectable={false} fitView>
          <Background />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>
    </section>
  );
}

function RunNode({ data }: { data: { node: SemanticNodeDto } }) {
  const Icon = data.node.kind === "dataset" ? Database : data.node.kind === "evaluator" ? Gavel : data.node.kind === "candidate" ? Bot : GitBranch;
  return (
    <div className="relative min-w-[220px] rounded-lg border border-line bg-surface shadow-sm">
      <Handle type="target" position={Position.Left} className="!left-[-5px]" />
      <div className="flex items-center gap-2 border-b border-line px-3 py-2">
        <Icon size={15} className="text-accent" />
        <strong className="truncate text-sm">{data.node.title}</strong>
      </div>
      <div className="p-3 text-xs font-mono text-muted">{data.node.id}</div>
      <Handle type="source" position={Position.Right} className="!right-[-5px]" />
    </div>
  );
}

function LeaderboardsSection({ data }: { data: GraphRunDetail }) {
  return (
    <section className="panel grid gap-4 p-4">
      <h2 className="text-sm font-bold">Leaderboard</h2>
      {data.leaderboards.map((group) => (
        <DataTable key={group.title}>
          <Table>
            <thead className="border-b border-line bg-surface-muted text-xs text-muted">
              <tr><th className="p-2">Rank</th><th className="p-2">Candidate</th><th className="p-2">ELO</th><th className="p-2">W-L-T</th></tr>
            </thead>
            <tbody>
              {group.rows.map((row, index) => (
                <tr key={row.entity_key} className="border-b border-line last:border-0">
                  <td className="p-2 text-muted">{index + 1}</td>
                  <td className="p-2 font-semibold">{row.label}</td>
                  <td className="p-2">{row.rating.toFixed(1)}</td>
                  <td className="p-2">{row.wins}-{row.losses}-{row.ties}</td>
                </tr>
              ))}
            </tbody>
          </Table>
        </DataTable>
      ))}
    </section>
  );
}

function HumanEvalSection({ runId, pairs, onChanged }: { runId: number; pairs: GraphPairDto[]; onChanged: () => void }) {
  const humanPairs = pairs.filter((pair) => !pair.winner);
  const submit = useMutation({
    mutationFn: ({ pair, winner, reasoning, reviewer }: { pair: GraphPairDto; winner: "A" | "B" | "TIE"; reasoning: string; reviewer: string }) => client.submitHumanEval(runId, pair.id, winner, reasoning, reviewer),
    onSuccess: onChanged,
  });
  if (!pairs.length) return null;
  return (
    <section className="panel grid gap-4 p-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-bold">Human Review</h2>
        <span className="text-xs text-muted">{humanPairs.length} pending · {pairs.length - humanPairs.length} complete</span>
      </div>
      {humanPairs.slice(0, 20).map((pair) => <HumanPair key={pair.id} pair={pair} onSubmit={(winner, reasoning, reviewer) => submit.mutate({ pair, winner, reasoning, reviewer })} />)}
    </section>
  );
}

function HumanPair({ pair, onSubmit }: { pair: GraphPairDto; onSubmit: (winner: "A" | "B" | "TIE", reasoning: string, reviewer: string) => void }) {
  const [reasoning, setReasoning] = useState("");
  const [reviewer, setReviewer] = useState("");
  return (
    <article className="grid gap-3 rounded-md border border-line bg-surface-muted p-3">
      <div className="flex justify-between gap-3 text-sm">
        <strong>{pair.item_key}</strong>
        <span className="text-muted">{pair.a_lineage_key} vs {pair.b_lineage_key}</span>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <pre className="max-h-64 overflow-auto rounded bg-surface p-3 text-xs">{pair.output_a || "No output"}</pre>
        <pre className="max-h-64 overflow-auto rounded bg-surface p-3 text-xs">{pair.output_b || "No output"}</pre>
      </div>
      <Input placeholder="Reviewer" value={reviewer} onChange={(event) => setReviewer(event.target.value)} />
      <Textarea placeholder="Reasoning" value={reasoning} onChange={(event) => setReasoning(event.target.value)} />
      <div className="flex gap-2">
        <Button type="button" onClick={() => onSubmit("A", reasoning, reviewer)}>A</Button>
        <Button type="button" onClick={() => onSubmit("B", reasoning, reviewer)}>B</Button>
        <Button type="button" variant="subtle" onClick={() => onSubmit("TIE", reasoning, reviewer)}>Tie</Button>
      </div>
    </article>
  );
}

function OutputBrowser({ invocations }: { invocations: GraphInvocationDto[] }) {
  const [openId, setOpenId] = useState<number | null>(null);
  const groups = useMemo(() => {
    const map = new Map<string, GraphInvocationDto[]>();
    invocations.forEach((invocation) => {
      const key = invocation.kind === "llm_judge" ? `Judge: ${invocation.evaluator_id}` : `Stage: ${invocation.stage_id} / ${invocation.candidate_id}`;
      map.set(key, [...(map.get(key) || []), invocation]);
    });
    return [...map.entries()];
  }, [invocations]);
  return (
    <section className="grid gap-4">
      <h2 className="text-sm font-bold">Model Calls</h2>
      {groups.map(([title, rows]) => (
        <div key={title} className="panel grid gap-3 p-4">
          <h3 className="text-sm font-bold">{title}</h3>
          {rows.map((invocation) => (
            <article key={invocation.id} className="rounded-md border border-line bg-surface p-3">
              <button className="flex w-full items-center justify-between text-left" onClick={() => setOpenId(openId === invocation.id ? null : invocation.id)}>
                <span className="font-semibold">{invocation.item_key} · {invocation.lineage_key}</span>
                <StatusPill status={invocation.status} />
              </button>
              {openId === invocation.id ? (
                <div className="mt-3 grid gap-3 text-sm">
                  {invocation.error ? <p className="text-danger">{invocation.error}</p> : null}
                  <pre className="max-h-96 overflow-auto rounded-md bg-surface-muted p-3">{invocation.output_json || invocation.output_raw || "No output"}</pre>
                  <details>
                    <summary className="cursor-pointer text-muted">Rendered prompt</summary>
                    <pre className="mt-2 max-h-96 overflow-auto rounded-md bg-surface-muted p-3">{invocation.rendered_prompt}</pre>
                  </details>
                </div>
              ) : null}
            </article>
          ))}
        </div>
      ))}
    </section>
  );
}
