import type { GraphDetail, GraphPairDto, GraphRunDetail, GraphRunSummary, LeaderboardView, ProjectDetail, ProjectSummary, ValidationResult } from "./types";

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
  createGraph: (project_id: number, name: string, spec?: Record<string, unknown>) => api(`/graphs`, { method: "POST", body: { project_id, name, spec } }),
  graph: (id: number) => api<GraphDetail>(`/graphs/${id}`),
  updateGraph: (id: number, body: { name?: string; spec?: Record<string, unknown>; layout?: Record<string, unknown> }) => api<GraphDetail>(`/graphs/${id}`, { method: "PATCH", body }),
  renameGraph: (id: number, name: string) => api<GraphDetail>(`/graphs/${id}`, { method: "PATCH", body: { name } }),
  validateSpec: (spec: Record<string, unknown>) => api<ValidationResult>("/graphs/validate-spec", { method: "POST", body: spec }),
  replaceSpec: (id: number, spec: Record<string, unknown>) => api<GraphDetail>(`/graphs/${id}/spec`, { method: "PUT", body: spec }),
  forkGraph: (id: number) => api(`/graphs/${id}/fork`, { method: "POST" }),
  deleteGraph: (id: number) => api<{ ok: true }>(`/graphs/${id}`, { method: "DELETE" }),
  launchGraph: (id: number, run_mode: "test" | "full", max_concurrency: number) =>
    api<GraphRunSummary>(`/graphs/${id}/launch`, { method: "POST", body: { run_mode, max_concurrency } }),
  graphRun: (id: number, leaderboardView: LeaderboardView = "aggregate") => api<GraphRunDetail>(`/graph-runs/${id}?leaderboard_view=${leaderboardView}`),
  stopRun: (id: number) => api<GraphRunSummary>(`/graph-runs/${id}/stop`, { method: "POST" }),
  continueRun: (id: number) => api<GraphRunSummary>(`/graph-runs/${id}/continue`, { method: "POST" }),
  retryFailures: (id: number) => api<GraphRunSummary>(`/graph-runs/${id}/retry-failures`, { method: "POST" }),
  humanEvals: (id: number) => api<GraphPairDto[]>(`/graph-runs/${id}/human-evals`),
  submitHumanEval: (runId: number, pairId: number, winner: "A" | "B" | "TIE", reasoning: string, human_reviewer: string) =>
    api<GraphPairDto>(`/graph-runs/${runId}/human-evals/${pairId}`, { method: "POST", body: { winner, reasoning, human_reviewer } }),
  judgeSummary: (id: number, leaderboard_view: LeaderboardView, top_entity_key = "") =>
    api<{ ok: true }>(`/graph-runs/${id}/judge-summary`, { method: "POST", body: { leaderboard_view, top_entity_key } })
};
