export type StatusValue = "pending" | "running" | "complete" | "failed" | "paused";
export type GraphStatusValue = "draft" | "running" | "complete" | "failed" | "paused";
export type NodeKind = "dataset" | "prompt" | "constant" | "model" | "judge";
export type LeaderboardView = "aggregate" | "overall" | "chain";

export type GraphRunSummary = {
  id: number;
  graph_id: number;
  name: string;
  status: StatusValue;
  max_concurrency: number;
  sample_size: number | null;
  error: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
};

export type ProjectSummary = {
  id: number;
  name: string;
  created_at: string;
  graph_count: number;
  recent_graph_runs: GraphRunSummary[];
};

export type GraphSummary = {
  id: number;
  project_id: number;
  name: string;
  status: GraphStatusValue;
  last_run_id: number | null;
  created_at: string;
  updated_at: string;
};

export type ProjectDetail = ProjectSummary & {
  graphs: GraphSummary[];
};

export type GraphNodeDto = {
  id: number;
  graph_id: number;
  kind: NodeKind | string;
  title: string;
  body: string;
  config: Record<string, unknown>;
  x: number;
  y: number;
  width: number;
  height: number;
  input_sockets: string[];
  output_sockets: string[];
  created_at: string;
  updated_at: string;
};

export type GraphEdgeDto = {
  id: number;
  graph_id: number;
  from_node_id: number;
  from_socket: string;
  to_node_id: number;
  to_socket: string;
  created_at: string;
};

export type GraphPlanDto = {
  transcript_count: number;
  prompt_stage_count: number;
  generator_model_count: number;
  judge_model_count: number;
  pair_count: number;
  sampled_matches_per_transcript: number;
  generation_calls: number;
  match_count: number;
  judge_calls: number;
  swap_multiplier: number;
  warnings: string[];
};

export type GraphDetail = {
  graph: GraphSummary;
  nodes: GraphNodeDto[];
  edges: GraphEdgeDto[];
  plan: GraphPlanDto;
  latest_run: GraphRunSummary | null;
};

export type GraphProgress = {
  total: number;
  pending: number;
  running: number;
  complete: number;
  failed: number;
};

export type GraphDiagnostic = {
  level: "info" | "warning" | "error";
  message: string;
};

export type GraphLeaderboardRow = {
  entity_key: string;
  label: string;
  node_id: number | null;
  rating: number;
  wins: number;
  losses: number;
  ties: number;
  avg_tokens: string;
  favorites: { id: number; title: string }[];
};

export type GraphLeaderboardGroup = {
  title: string;
  judge_prompt_node_id: number | null;
  view_mode: LeaderboardView;
  rows: GraphLeaderboardRow[];
};

export type GraphInvocationDto = {
  id: number;
  graph_run_id: number;
  node_id: number;
  model_node_id: number | null;
  node_title: string;
  model_title: string | null;
  item_key: string;
  stage_index: number;
  status: StatusValue;
  rendered_prompt: string;
  output_raw: string | null;
  output_json: string | null;
  error: string | null;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  duration_seconds: number | null;
  output_tokens_per_second: number | null;
  cost: number | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
};

export type GraphRunAnalysisDto = {
  id: number;
  graph_run_id: number;
  top_model_node_id: number;
  judge_prompt_node_id: number | null;
  leaderboard_view: string;
  top_entity_key: string;
  top_entity_label: string;
  model_id: string;
  win_sample_size: number;
  loss_sample_size: number;
  summary: string;
  created_at: string;
};

export type GraphRunDetail = {
  run: GraphRunSummary;
  graph: GraphSummary;
  nodes: GraphNodeDto[];
  edges: GraphEdgeDto[];
  progress: GraphProgress;
  node_progress: Record<number, GraphProgress>;
  diagnostics: GraphDiagnostic[];
  leaderboards: GraphLeaderboardGroup[];
  invocations: GraphInvocationDto[];
  analyses: GraphRunAnalysisDto[];
};

