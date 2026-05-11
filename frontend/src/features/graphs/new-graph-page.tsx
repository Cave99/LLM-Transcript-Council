import { useMutation, useQuery } from "@tanstack/react-query";
import { useNavigate, useSearchParams } from "react-router-dom";
import { client } from "../../api/client";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Select } from "../../components/ui/select";

export function NewGraphPage() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const { data: projects = [] } = useQuery({ queryKey: ["projects"], queryFn: client.projects });
  const create = useMutation({
    mutationFn: ({ projectId, name }: { projectId: number; name: string }) => client.createGraph(projectId, name),
    onSuccess: (graph: any) => navigate(`/graphs/${graph.id}`)
  });
  const defaultProject = Number(params.get("project_id")) || projects[0]?.id || "";

  return (
    <div className="grid max-w-xl gap-6">
      <section className="border-b border-line pb-6">
        <h1 className="text-3xl font-extrabold">New Graph</h1>
        <p className="mt-2 text-muted">Create an editable graph draft inside a project.</p>
      </section>
      <form
        className="panel grid gap-4 p-5"
        onSubmit={(event) => {
          event.preventDefault();
          const form = new FormData(event.currentTarget);
          create.mutate({ projectId: Number(form.get("project_id")), name: String(form.get("name") || "Untitled graph") });
        }}
      >
        <label className="grid gap-1 text-sm font-semibold">
          Project
          <Select name="project_id" defaultValue={String(defaultProject)} required>
            {projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}
          </Select>
        </label>
        <label className="grid gap-1 text-sm font-semibold">
          Graph name
          <Input name="name" placeholder="Payment coaching comparison" required />
        </label>
        <Button disabled={create.isPending}>Create Graph</Button>
      </form>
    </div>
  );
}
