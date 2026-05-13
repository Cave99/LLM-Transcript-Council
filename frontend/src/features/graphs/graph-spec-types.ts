import type { GraphPlanDto } from "../../api/types";

export type GraphSpec = {
  version: 1;
  dataset: { provider: "markdown_folder" | "csv"; config: Record<string, unknown> };
  constants?: Record<string, string>;
  stages: StageSpec[];
  evaluators: EvaluatorSpec[];
};

export type StageSpec = {
  id: string;
  title?: string;
  fanout?: "matrix";
  upstream_output?: "raw" | "json";
  candidates: CandidateSpec[];
};

export type CandidateSpec = {
  id: string;
  title?: string;
  model?: string;
  prompt_path?: string | null;
  prompt_inline?: string | null;
  params?: { temperature?: number; retry_count?: number; reasoning_effort?: string | null };
};

export type EvaluatorSpec = {
  id: string;
  title?: string;
  type: "llm_pairwise" | "human_pairwise";
  target_stage: string;
  model?: string;
  prompt_path?: string | null;
  prompt_inline?: string | null;
  params?: { temperature?: number; retry_count?: number; reasoning_effort?: string | null };
  pairing: { sample_pct?: number; swap?: boolean; seed?: string | null };
  output?: { winner_key?: string; reasoning_key?: string };
};

export type GraphLayout = Record<string, { x: number; y: number }>;
export type NewNodeKind = "stage" | "llm_pairwise" | "human_pairwise";

export function uniqueId(prefix: string, existing: string[]) {
  let index = existing.length + 1;
  let candidate = `${prefix}_${index}`;
  while (existing.includes(candidate)) {
    index += 1;
    candidate = `${prefix}_${index}`;
  }
  return candidate;
}

export function allCandidateIds(spec: GraphSpec) {
  return spec.stages.flatMap((stage) => stage.candidates.map((candidate) => candidate.id));
}

export function newStage(id: string): StageSpec {
  return {
    id,
    title: "New stage",
    fanout: "matrix",
    upstream_output: "raw",
    candidates: [],
  };
}

export function newCandidate(id: string): CandidateSpec {
  return {
    id,
    title: "New candidate",
    model: "",
    prompt_inline: "",
    prompt_path: null,
    params: { temperature: 0.2, retry_count: 2, reasoning_effort: null },
  };
}

export function newEvaluator(id: string, type: NewNodeKind, targetStage: string): EvaluatorSpec {
  const isHuman = type === "human_pairwise";
  return {
    id,
    title: isHuman ? "Human review" : "LLM judge",
    type: isHuman ? "human_pairwise" : "llm_pairwise",
    target_stage: targetStage,
    model: isHuman ? "" : "google/gemini-3-flash-preview",
    prompt_inline: isHuman ? null : "## Output A\n{{ output_a }}\n\n## Output B\n{{ output_b }}\n\nReturn JSON with `reasoning` and `winner` as A, B, or TIE.",
    prompt_path: null,
    pairing: { sample_pct: 100, swap: false, seed: null },
    output: { winner_key: "winner", reasoning_key: "reasoning" },
    params: { temperature: 0, retry_count: 2, reasoning_effort: null },
  };
}

export function planStats(plan: GraphPlanDto) {
  return [
    ["Items", plan.transcript_count],
    ["Stages", plan.stage_count],
    ["Candidates", plan.candidate_count],
    ["Evaluators", plan.evaluator_count],
    ["Generation calls", plan.generation_calls],
    ["Pairs", plan.pair_count],
    ["Judge calls", plan.judge_calls],
    ["Human reviews", plan.human_review_count],
  ] as const;
}
