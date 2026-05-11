import { useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { RotateCcw, Square, StepForward } from "lucide-react";
import { client } from "../../api/client";
import { queryClient } from "../../api/queries";
import type { GraphInvocationDto, LeaderboardView } from "../../api/types";
import { Button } from "../../components/ui/button";
import { Progress } from "../../components/ui/progress";
import { Table } from "../../components/ui/table";
import { StatusPill } from "../../components/status-pill";
import { DataTable } from "../../components/data-table";

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

      <OutputBrowser invocations={data.invocations} />
    </div>
  );
}

function OutputBrowser({ invocations }: { invocations: GraphInvocationDto[] }) {
  const [openId, setOpenId] = useState<number | null>(null);
  const groups = useMemo(() => {
    const map = new Map<string, GraphInvocationDto[]>();
    invocations.forEach((invocation) => {
      const key = invocation.model_title || invocation.node_title;
      map.set(key, [...(map.get(key) || []), invocation]);
    });
    return [...map.entries()];
  }, [invocations]);

  return (
    <section className="grid gap-4">
      <h2 className="text-sm font-bold">Model Outputs</h2>
      {groups.map(([label, rows]) => (
        <div key={label} className="panel grid gap-2 p-4">
          <h3 className="text-sm font-bold">{label}</h3>
          {rows.map((invocation) => (
            <article key={invocation.id} className="rounded-md border border-line bg-surface p-3">
              <button className="flex w-full items-center justify-between text-left" onClick={() => setOpenId(openId === invocation.id ? null : invocation.id)}>
                <span className="font-semibold">{invocation.item_key}</span>
                <StatusPill status={invocation.status} />
              </button>
              {openId === invocation.id ? (
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
          ))}
        </div>
      ))}
    </section>
  );
}
