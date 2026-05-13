export type StatusValue = "pending" | "running" | "complete" | "failed" | "paused";
export type GraphStatusValue = "draft" | "running" | "complete" | "failed" | "paused";
export type LeaderboardView = "aggregate";

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
  spec_hash: string;
  created_at: string;
  updated_at: string;
};

export type ProjectDetail = ProjectSummary & {
  graphs: GraphSummary[];
};

export type SemanticNodeDto = {
  id: string;
  kind: string;
  title: string;
  x: number;
  y: number;
};

export type SemanticEdgeDto = {
  id: string;
  source: string;
  target: string;
};

export type GraphPlanDto = {
  transcript_count: number;
  stage_count: number;
  candidate_count: number;
  evaluator_count: number;
  generation_calls: number;
  pair_count: number;
  judge_calls: number;
  human_review_count: number;
  warnings: string[];
};

export type GraphDetail = {
  graph: GraphSummary;
  spec: Record<string, unknown>;
  layout: Record<string, { x: number; y: number }>;
  nodes: SemanticNodeDto[];
  edges: SemanticEdgeDto[];
  plan: GraphPlanDto;
  latest_run: GraphRunSummary | null;
  graph_runs: GraphRunSummary[];
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
  rating: number;
  wins: number;
  losses: number;
  ties: number;
  avg_tokens: string;
  favorites: { id: number; title: string }[];
};

export type GraphLeaderboardGroup = {
  title: string;
  view_mode: LeaderboardView;
  rows: GraphLeaderboardRow[];
};

export type GraphInvocationDto = {
  id: number;
  graph_run_id: number;
  kind: string;
  stage_id: string;
  candidate_id: string | null;
  evaluator_id: string | null;
  lineage_key: string;
  model_id: string;
  item_key: string;
  stage_index: number;
  status: StatusValue;
  rendered_prompt: string;
  output_raw: string | null;
  output_json: string | null;
  error: string | null;
  error_category: string | null;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  duration_seconds: number | null;
  output_tokens_per_second: number | null;
  cost: number | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
};

export type GraphPairDto = {
  id: number;
  graph_run_id: number;
  evaluator_id: string;
  target_stage_id: string;
  item_key: string;
  pair_key: string;
  a_lineage_key: string;
  b_lineage_key: string;
  direction: string;
  status: StatusValue;
  output_a: string | null;
  output_b: string | null;
  winner: string | null;
  reasoning: string;
  human_reviewer: string | null;
};

export type GraphRunAnalysisDto = {
  id: number;
  graph_run_id: number;
  evaluator_id: string;
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
  nodes: SemanticNodeDto[];
  edges: SemanticEdgeDto[];
  progress: GraphProgress;
  diagnostics: GraphDiagnostic[];
  leaderboards: GraphLeaderboardGroup[];
  invocations: GraphInvocationDto[];
  human_evals: GraphPairDto[];
  analyses: GraphRunAnalysisDto[];
};

export type ValidationResult = {
  valid: boolean;
  errors: { code: string; path: string; message: string }[];
  warnings: { code: string; path: string; message: string }[];
};
