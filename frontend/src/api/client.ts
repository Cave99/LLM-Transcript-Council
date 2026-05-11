import type { GraphDetail, GraphRunDetail, GraphRunSummary, LeaderboardView, NodeKind, ProjectDetail, ProjectSummary } from "./types";

type RequestOptions = {
  method?: string;
  body?: unknown;
};

export async function api<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const response = await fetch(`/api${path}`, {
    method: options.method ?? "GET",
    headers: options.body === undefined ? undefined : { "Content-Type": "application/json" },
    body: options.body === undefined ? undefined : JSON.stringify(options.body)
  });
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try {
      const payload = await response.json();
      message = payload.detail?.message ?? payload.detail ?? message;
    } catch {
      // Keep the HTTP status text.
    }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

export const client = {
  projects: () => api<ProjectSummary[]>("/projects"),
  createProject: (name: string) => api<ProjectSummary>("/projects", { method: "POST", body: { name } }),
  project: (id: number) => api<ProjectDetail>(`/projects/${id}`),
  renameProject: (id: number, name: string) => api<ProjectSummary>(`/projects/${id}`, { method: "PATCH", body: { name } }),
  deleteProject: (id: number) => api<{ ok: true }>(`/projects/${id}`, { method: "DELETE" }),
  createGraph: (project_id: number, name: string) => api(`/graphs`, { method: "POST", body: { project_id, name } }),
  graph: (id: number) => api<GraphDetail>(`/graphs/${id}`),
  renameGraph: (id: number, name: string) => api(`/graphs/${id}`, { method: "PATCH", body: { name } }),
  forkGraph: (id: number) => api(`/graphs/${id}/fork`, { method: "POST" }),
  deleteGraph: (id: number) => api<{ ok: true }>(`/graphs/${id}`, { method: "DELETE" }),
  launchGraph: (id: number, run_mode: "test" | "full", max_concurrency: number) =>
    api<GraphRunSummary>(`/graphs/${id}/launch`, { method: "POST", body: { run_mode, max_concurrency } }),
  createNode: (graphId: number, kind: NodeKind, x?: number, y?: number, title?: string) =>
    api(`/graphs/${graphId}/nodes`, { method: "POST", body: { kind, x, y, title } }),
  updateNode: (nodeId: number, title: string, body: string, config: Record<string, unknown>) =>
    api(`/nodes/${nodeId}`, { method: "PATCH", body: { title, body, config } }),
  updateNodePosition: (nodeId: number, x: number, y: number, width?: number, height?: number) =>
    api(`/nodes/${nodeId}/position`, { method: "PATCH", body: { x, y, width, height } }),
  deleteNode: (nodeId: number) => api<{ ok: true }>(`/nodes/${nodeId}`, { method: "DELETE" }),
  createEdge: (graphId: number, from_node_id: number, from_socket: string, to_node_id: number, to_socket: string) =>
    api(`/graphs/${graphId}/edges`, { method: "POST", body: { from_node_id, from_socket, to_node_id, to_socket } }),
  deleteEdge: (edgeId: number) => api<{ ok: true }>(`/edges/${edgeId}`, { method: "DELETE" }),
  graphRun: (id: number, leaderboardView: LeaderboardView = "aggregate") => api<GraphRunDetail>(`/graph-runs/${id}?leaderboard_view=${leaderboardView}`),
  stopRun: (id: number) => api<GraphRunSummary>(`/graph-runs/${id}/stop`, { method: "POST" }),
  continueRun: (id: number) => api<GraphRunSummary>(`/graph-runs/${id}/continue`, { method: "POST" }),
  retryFailures: (id: number) => api<GraphRunSummary>(`/graph-runs/${id}/retry-failures`, { method: "POST" }),
  judgeSummary: (id: number, leaderboard_view: LeaderboardView, judge_prompt_node_id?: number | null, top_entity_key = "") =>
    api<{ ok: true }>(`/graph-runs/${id}/judge-summary`, { method: "POST", body: { leaderboard_view, judge_prompt_node_id, top_entity_key } })
};

