import { useMutation, useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Copy, GitFork, Plus, Trash2 } from "lucide-react";
import { client } from "../../api/client";
import { queryClient } from "../../api/queries";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { EmptyState } from "../../components/empty-state";
import { StatusPill } from "../../components/status-pill";
import { confirmDanger } from "../../components/confirm-dialog";

export function ProjectDetailPage() {
  const navigate = useNavigate();
  const projectId = Number(useParams().projectId);
  const { data: project, isLoading, error } = useQuery({ queryKey: ["project", projectId], queryFn: () => client.project(projectId), enabled: Number.isFinite(projectId) });
  const rename = useMutation({
    mutationFn: (name: string) => client.renameProject(projectId, name),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["project", projectId] })
  });
  const createGraph = useMutation({
    mutationFn: (name: string) => client.createGraph(projectId, name),
    onSuccess: (graph: any) => navigate(`/graphs/${graph.id}`)
  });
  const deleteGraph = useMutation({
    mutationFn: client.deleteGraph,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["project", projectId] })
  });
  const forkGraph = useMutation({
    mutationFn: client.forkGraph,
    onSuccess: (graph: any) => navigate(`/graphs/${graph.id}`)
  });

  if (isLoading) return <p className="text-sm text-muted">Loading project...</p>;
  if (error || !project) return <p className="text-sm text-danger">{String(error || "Project not found")}</p>;

  return (
    <div className="grid gap-7">
      <section className="flex items-end justify-between gap-6 border-b border-line pb-6">
        <div className="grid gap-3">
          <h1 className="text-3xl font-extrabold">{project.name}</h1>
          <form
            className="flex max-w-md gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              const name = String(new FormData(event.currentTarget).get("name") || "").trim();
              if (name) rename.mutate(name);
            }}
          >
            <Input name="name" defaultValue={project.name} aria-label="Rename project" />
            <Button type="submit" variant="subtle">Rename</Button>
          </form>
        </div>
        <form
          className="flex min-w-80 gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            const name = String(new FormData(event.currentTarget).get("name") || "").trim();
            if (name) createGraph.mutate(name);
            event.currentTarget.reset();
          }}
        >
          <Input name="name" placeholder="Graph name" />
          <Button disabled={createGraph.isPending}>
            <Plus size={16} />
            New Graph
          </Button>
        </form>
      </section>

      {project.graphs.length === 0 ? <EmptyState title="No graphs yet" body="Create a graph to model datasets, prompts, models, and judges." /> : null}
      <section className="grid gap-3">
        {project.graphs.map((graph) => (
          <div key={graph.id} className="panel grid grid-cols-[1fr_auto] items-start gap-4 p-4 transition hover:border-line-strong hover:bg-surface-raised">
            <Link to={`/graphs/${graph.id}`} className="grid gap-2">
              <div className="flex items-center gap-3">
                <h2 className="text-base font-bold hover:text-accent">{graph.name}</h2>
                <StatusPill status={graph.status} />
              </div>
              <p className="text-sm text-muted">Updated {new Date(graph.updated_at).toLocaleString()}</p>
            </Link>
            <div className="flex gap-2">
              <Button type="button" variant="subtle" onClick={() => forkGraph.mutate(graph.id)}>
                <GitFork size={15} />
                Fork
              </Button>
              {graph.last_run_id ? (
                <Button type="button" variant="subtle" onClick={() => navigate(`/graph-runs/${graph.last_run_id}`)}>
                  <Copy size={15} />
                  Run
                </Button>
              ) : null}
              <Button
                type="button"
                variant="danger"
                onClick={() => {
                  if (confirmDanger(`Delete graph "${graph.name}"?`)) deleteGraph.mutate(graph.id);
                }}
              >
                <Trash2 size={15} />
                Delete
              </Button>
            </div>
          </div>
        ))}
      </section>
    </div>
  );
}

