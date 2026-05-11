import { useMutation, useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { Plus, Trash2 } from "lucide-react";
import { client } from "../../api/client";
import { queryClient } from "../../api/queries";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { EmptyState } from "../../components/empty-state";
import { StatusPill } from "../../components/status-pill";
import { confirmDanger } from "../../components/confirm-dialog";

export function ProjectsPage() {
  const navigate = useNavigate();
  const { data: projects = [], isLoading, error } = useQuery({ queryKey: ["projects"], queryFn: client.projects });
  const create = useMutation({
    mutationFn: client.createProject,
    onSuccess: (project) => {
      queryClient.invalidateQueries({ queryKey: ["projects"] });
      navigate(`/projects/${project.id}`);
    }
  });
  const remove = useMutation({
    mutationFn: client.deleteProject,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["projects"] })
  });

  return (
    <div className="grid gap-7">
      <section className="flex items-end justify-between gap-6 border-b border-line pb-6">
        <div className="grid gap-2">
          <h1 className="text-3xl font-extrabold tracking-normal">Projects</h1>
          <p className="max-w-3xl text-muted">Create local evaluation workspaces for prompt graphs, model comparisons, and judge evidence.</p>
        </div>
        <form
          className="flex min-w-80 gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            const form = new FormData(event.currentTarget);
            const name = String(form.get("name") || "").trim();
            if (name) create.mutate(name);
            event.currentTarget.reset();
          }}
        >
          <Input name="name" placeholder="Project name" />
          <Button disabled={create.isPending}>
            <Plus size={16} />
            Create
          </Button>
        </form>
      </section>

      {isLoading ? <p className="text-sm text-muted">Loading projects...</p> : null}
      {error ? <p className="text-sm text-danger">{String(error)}</p> : null}
      {!isLoading && projects.length === 0 ? <EmptyState title="No projects yet" body="Create a project to start drafting graph evaluations." /> : null}

      <section className="grid gap-3">
        {projects.map((project) => (
          <div key={project.id} className="panel grid grid-cols-[1fr_auto] items-start gap-4 p-4 transition hover:border-line-strong hover:bg-surface-raised">
            <Link to={`/projects/${project.id}`} className="grid gap-2">
              <h2 className="text-base font-bold hover:text-accent">{project.name}</h2>
              <p className="text-sm text-muted">{project.graph_count} graph{project.graph_count === 1 ? "" : "s"} · created {new Date(project.created_at).toLocaleDateString()}</p>
              {project.recent_graph_runs.length ? (
                <div className="flex flex-wrap gap-2 pt-1">
                  {project.recent_graph_runs.slice(0, 3).map((run) => (
                    <span key={run.id} className="inline-flex items-center gap-2 text-xs text-muted">
                      <StatusPill status={run.status} />
                      {run.name}
                    </span>
                  ))}
                </div>
              ) : null}
            </Link>
            <Button
              type="button"
              variant="danger"
              disabled={remove.isPending}
              onClick={() => {
                if (confirmDanger(`Delete project "${project.name}" and all graph runs?`)) remove.mutate(project.id);
              }}
            >
              <Trash2 size={15} />
              Delete
            </Button>
          </div>
        ))}
      </section>
    </div>
  );
}

