import { Bot, Database, Gavel, GitBranch, Plus } from "lucide-react";
import { Handle, Position } from "reactflow";
import type { SemanticNodeDto } from "../../api/types";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Select } from "../../components/ui/select";
import type { CandidateSpec, EvaluatorSpec, GraphSpec, StageSpec } from "./graph-spec-types";
import { allCandidateIds, newCandidate, uniqueId } from "./graph-spec-types";

type NodeData = {
  node: SemanticNodeDto;
  spec: GraphSpec;
  onSelect: (id: string) => void;
  onStageChange: (id: string, stage: StageSpec) => void;
  onCandidateChange: (stageId: string, id: string, candidate: CandidateSpec) => void;
  onEvaluatorChange: (id: string, evaluator: EvaluatorSpec) => void;
};

export function SemanticNode({ data }: { data: NodeData }) {
  const Icon = data.node.kind === "dataset" ? Database : data.node.kind === "evaluator" ? Gavel : data.node.kind === "candidate" ? Bot : GitBranch;
  const stage = data.spec.stages?.find((item) => item.id === data.node.id);
  const candidateStage = data.spec.stages?.find((item) => item.candidates.some((candidate) => candidate.id === data.node.id));
  const candidate = candidateStage?.candidates.find((item) => item.id === data.node.id);
  const evaluator = data.spec.evaluators?.find((item) => item.id === data.node.id);
  return (
    <div className="relative min-w-[320px] max-w-[380px] rounded-lg border border-line bg-surface shadow-sm">
      <Handle type="target" position={Position.Left} className="!left-[-5px]" />
      <div className="semantic-node-drag-handle flex cursor-grab items-center gap-2 border-b border-line px-3 py-2 active:cursor-grabbing">
        <Icon size={15} className="text-accent" />
        <strong className="truncate text-sm">{data.node.title}</strong>
      </div>
      <div className="nodrag nowheel grid gap-2 p-3 text-xs text-muted">
        <span className="font-mono">{data.node.id}</span>
        <span>{data.node.kind}</span>
        {stage ? <CanvasStageFields spec={data.spec} stage={stage} onChange={(next) => data.onStageChange(stage.id, next)} onOpen={() => data.onSelect(stage.id)} /> : null}
        {candidate && candidateStage ? <CanvasCandidateFields candidate={candidate} onChange={(next) => data.onCandidateChange(candidateStage.id, candidate.id, next)} onOpen={() => data.onSelect(candidate.id)} /> : null}
        {evaluator ? <CanvasEvaluatorFields spec={data.spec} evaluator={evaluator} onChange={(next) => data.onEvaluatorChange(evaluator.id, next)} onOpen={() => data.onSelect(evaluator.id)} /> : null}
      </div>
      <Handle type="source" position={Position.Right} className="!right-[-5px]" />
    </div>
  );
}

function CanvasStageFields({ spec, stage, onChange, onOpen }: { spec: GraphSpec; stage: StageSpec; onChange: (stage: StageSpec) => void; onOpen: () => void }) {
  const addCandidate = () => {
    const id = uniqueId("candidate", allCandidateIds(spec));
    onChange({ ...stage, candidates: [...stage.candidates, newCandidate(id)] });
  };
  return (
    <div className="grid gap-2">
      <Input className="h-8 text-xs" value={stage.title || ""} onChange={(event) => onChange({ ...stage, title: event.target.value })} aria-label="Stage title" />
      <div className="flex items-center justify-between gap-2">
        <div className="text-[11px] font-bold uppercase text-muted">{stage.candidates.length} candidate{stage.candidates.length === 1 ? "" : "s"}</div>
        <Button type="button" variant="subtle" onClick={addCandidate}><Plus size={13} /> Candidate</Button>
      </div>
      {stage.candidates.length === 0 ? <p className="rounded-md border border-dashed border-line p-2 text-[11px] text-muted">No candidates yet. Add one here or in the inspector.</p> : null}
      <Button type="button" variant="subtle" onClick={onOpen}>Open Inspector</Button>
    </div>
  );
}

function CanvasCandidateFields({ candidate, onChange, onOpen }: { candidate: CandidateSpec; onChange: (candidate: CandidateSpec) => void; onOpen: () => void }) {
  return (
    <div className="grid gap-2">
      <Input className="h-8 text-xs" value={candidate.title || ""} onChange={(event) => onChange({ ...candidate, title: event.target.value })} aria-label={`${candidate.id} title`} placeholder="Candidate title" />
      <Input className="h-8 text-xs" value={candidate.model || ""} onChange={(event) => onChange({ ...candidate, model: event.target.value })} aria-label={`${candidate.id} model`} placeholder="model/provider" />
      <div className="grid grid-cols-2 gap-1">
        <Input className="h-8 text-xs" value={String(candidate.params?.temperature ?? 0)} onChange={(event) => onChange({ ...candidate, params: { ...(candidate.params || {}), temperature: Number(event.target.value) } })} aria-label={`${candidate.id} temperature`} placeholder="temp" />
        <Input className="h-8 text-xs" value={candidate.params?.reasoning_effort || ""} onChange={(event) => onChange({ ...candidate, params: { ...(candidate.params || {}), reasoning_effort: event.target.value || null } })} aria-label={`${candidate.id} reasoning`} placeholder="reasoning" />
      </div>
      <Button type="button" variant="subtle" onClick={onOpen}>Open Inspector</Button>
    </div>
  );
}

function CanvasEvaluatorFields({ spec, evaluator, onChange, onOpen }: { spec: GraphSpec; evaluator: EvaluatorSpec; onChange: (evaluator: EvaluatorSpec) => void; onOpen: () => void }) {
  return (
    <div className="grid gap-2">
      <Input className="h-8 text-xs" value={evaluator.title || ""} onChange={(event) => onChange({ ...evaluator, title: event.target.value })} aria-label="Evaluator title" />
      <Select className="h-8 text-xs" value={evaluator.target_stage || ""} onChange={(event) => onChange({ ...evaluator, target_stage: event.target.value })}>
        {spec.stages.map((stage) => <option key={stage.id} value={stage.id}>{stage.title || stage.id}</option>)}
      </Select>
      {evaluator.type === "llm_pairwise" ? <Input className="h-8 text-xs" value={evaluator.model || ""} onChange={(event) => onChange({ ...evaluator, model: event.target.value })} aria-label="Judge model" /> : <span className="font-mono">human_pairwise</span>}
      <div className="grid grid-cols-2 gap-1">
        <Input className="h-8 text-xs" value={String(evaluator.pairing?.sample_pct ?? 100)} onChange={(event) => onChange({ ...evaluator, pairing: { ...evaluator.pairing, sample_pct: Number(event.target.value) } })} aria-label="Sample percent" />
        <Select className="h-8 text-xs" value={String(Boolean(evaluator.pairing?.swap))} onChange={(event) => onChange({ ...evaluator, pairing: { ...evaluator.pairing, swap: event.target.value === "true" } })}>
          <option value="false">swap off</option>
          <option value="true">swap on</option>
        </Select>
      </div>
      <Button type="button" variant="subtle" onClick={onOpen}>Open Inspector</Button>
    </div>
  );
}
