import type { ReactNode } from "react";
import { Bot, Database, Gavel, GitBranch, Plus, Trash2 } from "lucide-react";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Select } from "../../components/ui/select";
import { Textarea } from "../../components/ui/textarea";
import type { CandidateSpec, EvaluatorSpec, GraphSpec, StageSpec } from "./graph-spec-types";
import { allCandidateIds, newCandidate, uniqueId } from "./graph-spec-types";

export function GraphInspector({ spec, selectedId, onSelect, onChange }: { spec: GraphSpec; selectedId: string; onSelect: (id: string) => void; onChange: (spec: GraphSpec) => void }) {
  const stage = spec.stages.find((item) => item.id === selectedId);
  const candidateStage = spec.stages.find((item) => item.candidates.some((candidate) => candidate.id === selectedId));
  const candidate = candidateStage?.candidates.find((item) => item.id === selectedId);
  const evaluator = spec.evaluators.find((item) => item.id === selectedId);
  if (selectedId === "dataset") {
    return (
      <div className="flex flex-col">
        <InspectorHeader icon={<Database size={16} />} title="Dataset" />
        <div className="grid gap-4 p-4">
          <Field label="Provider"><Select value={spec.dataset.provider} onChange={(event) => onChange({ ...spec, dataset: { ...spec.dataset, provider: event.target.value as "markdown_folder" | "csv" } })}><option value="markdown_folder">Markdown folder</option><option value="csv">CSV</option></Select></Field>
          <Field label="Path"><Input value={String(spec.dataset.config.path || "")} onChange={(event) => onChange({ ...spec, dataset: { ...spec.dataset, config: { ...spec.dataset.config, path: event.target.value } } })} /></Field>
        </div>
      </div>
    );
  }
  if (stage) return <StageInspector spec={spec} stage={stage} onSelect={onSelect} onChange={onChange} />;
  if (candidate && candidateStage) return <CandidateInspector spec={spec} stage={candidateStage} candidate={candidate} onSelect={onSelect} onChange={onChange} />;
  if (evaluator) return <EvaluatorInspector spec={spec} evaluator={evaluator} onSelect={onSelect} onChange={onChange} />;
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-3 p-6 text-center text-sm text-muted">
      <Database size={24} className="text-line-strong" />
      <p>Select a node to edit its properties.</p>
    </div>
  );
}

function InspectorHeader({ icon, title, action }: { icon: ReactNode; title: string; action?: ReactNode }) {
  return (
    <div className="sticky top-0 z-10 flex h-[57px] shrink-0 items-center justify-between gap-3 border-b border-line bg-surface-muted px-4">
      <div className="flex min-w-0 items-center gap-2">
        <span className="text-accent">{icon}</span>
        <h2 className="truncate text-sm font-bold">{title}</h2>
      </div>
      {action ? <div className="flex items-center gap-1">{action}</div> : null}
    </div>
  );
}

function StageInspector({ spec, stage, onSelect, onChange }: { spec: GraphSpec; stage: StageSpec; onSelect: (id: string) => void; onChange: (spec: GraphSpec) => void }) {
  const updateStage = (next: StageSpec) => onChange({ ...spec, stages: spec.stages.map((item) => item.id === stage.id ? next : item) });
  const deleteStage = () => {
    const nextStages = spec.stages.filter((item) => item.id !== stage.id);
    const fallback = nextStages.at(-1)?.id || "";
    onChange({ ...spec, stages: nextStages, evaluators: spec.evaluators.map((item) => item.target_stage === stage.id ? { ...item, target_stage: fallback } : item) });
    onSelect("dataset");
  };
  const addCandidate = () => {
    const id = uniqueId("candidate", allCandidateIds(spec));
    updateStage({ ...stage, candidates: [...stage.candidates, newCandidate(id)] });
  };
  return (
    <div className="flex flex-col">
      <InspectorHeader icon={<GitBranch size={16} />} title={stage.title || stage.id} action={<Button type="button" variant="danger" onClick={deleteStage}><Trash2 size={14} /></Button>} />
      <div className="grid gap-4 p-4">
        <Field label="Title"><Input value={stage.title || ""} onChange={(event) => updateStage({ ...stage, title: event.target.value })} /></Field>
        <Field label="Upstream output"><Select value={stage.upstream_output || "raw"} onChange={(event) => updateStage({ ...stage, upstream_output: event.target.value as "raw" | "json" })}><option value="raw">Raw</option><option value="json">JSON</option></Select></Field>
        <div className="border-t border-line pt-4">
          <div className="mb-3 flex items-center justify-between">
            <h3 className="text-xs font-bold uppercase text-muted">Candidates</h3>
            <Button type="button" variant="subtle" onClick={addCandidate}><Plus size={14} /> Candidate</Button>
          </div>
          <div className="grid gap-3">
            {stage.candidates.map((candidate) => (
              <CandidateEditor
                key={candidate.id}
                candidate={candidate}
                onChange={(next) => updateStage({ ...stage, candidates: stage.candidates.map((item) => item.id === candidate.id ? next : item) })}
                onDelete={() => updateStage({ ...stage, candidates: stage.candidates.filter((item) => item.id !== candidate.id) })}
              />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function CandidateEditor({ candidate, onChange, onDelete, showHeader = true }: { candidate: CandidateSpec; onChange: (candidate: CandidateSpec) => void; onDelete: () => void; showHeader?: boolean }) {
  return (
    <article className="grid gap-2 rounded-md border border-line bg-surface-muted p-3">
      {showHeader ? (
        <div className="flex items-center justify-between gap-2">
          <strong className="text-sm">{candidate.title || candidate.id}</strong>
          <Button type="button" variant="danger" onClick={onDelete}><Trash2 size={14} /></Button>
        </div>
      ) : null}
      <Field label="Title"><Input value={candidate.title || ""} onChange={(event) => onChange({ ...candidate, title: event.target.value })} /></Field>
      <Field label="Model"><Input value={candidate.model || ""} onChange={(event) => onChange({ ...candidate, model: event.target.value })} /></Field>
      <div className="grid grid-cols-2 gap-2">
        <Field label="Temperature"><Input value={String(candidate.params?.temperature ?? 0)} onChange={(event) => onChange({ ...candidate, params: { ...candidate.params, temperature: Number(event.target.value) } })} /></Field>
        <Field label="Reasoning"><Input value={candidate.params?.reasoning_effort || ""} onChange={(event) => onChange({ ...candidate, params: { ...candidate.params, reasoning_effort: event.target.value || null } })} /></Field>
      </div>
      <Field label="Prompt"><Textarea className="h-32 font-mono text-xs" value={candidate.prompt_inline || ""} onChange={(event) => onChange({ ...candidate, prompt_inline: event.target.value, prompt_path: null })} /></Field>
    </article>
  );
}

function CandidateInspector({ spec, stage, candidate, onSelect, onChange }: { spec: GraphSpec; stage: StageSpec; candidate: CandidateSpec; onSelect: (id: string) => void; onChange: (spec: GraphSpec) => void }) {
  const updateCandidate = (next: CandidateSpec) => {
    onChange({
      ...spec,
      stages: spec.stages.map((item) => item.id === stage.id ? { ...item, candidates: item.candidates.map((existing) => existing.id === candidate.id ? next : existing) } : item),
    });
  };
  const deleteCandidate = () => {
    onChange({
      ...spec,
      stages: spec.stages.map((item) => item.id === stage.id ? { ...item, candidates: item.candidates.filter((existing) => existing.id !== candidate.id) } : item),
    });
    onSelect(stage.id);
  };
  return (
    <div className="flex flex-col">
      <InspectorHeader icon={<Bot size={16} />} title={candidate.title || candidate.id} action={<Button type="button" variant="danger" onClick={deleteCandidate}><Trash2 size={14} /></Button>} />
      <div className="grid gap-4 p-4">
        <p className="text-xs text-muted">Stage: {stage.title || stage.id}</p>
        <CandidateEditor candidate={candidate} onChange={updateCandidate} onDelete={deleteCandidate} showHeader={false} />
      </div>
    </div>
  );
}

function EvaluatorInspector({ spec, evaluator, onSelect, onChange }: { spec: GraphSpec; evaluator: EvaluatorSpec; onSelect: (id: string) => void; onChange: (spec: GraphSpec) => void }) {
  const updateEvaluator = (next: EvaluatorSpec) => onChange({ ...spec, evaluators: spec.evaluators.map((item) => item.id === evaluator.id ? next : item) });
  const deleteEvaluator = () => {
    onChange({ ...spec, evaluators: spec.evaluators.filter((item) => item.id !== evaluator.id) });
    onSelect("dataset");
  };
  return (
    <div className="flex flex-col">
      <InspectorHeader icon={<Gavel size={16} />} title={evaluator.title || evaluator.id} action={<Button type="button" variant="danger" onClick={deleteEvaluator}><Trash2 size={14} /></Button>} />
      <div className="grid gap-4 p-4">
        <Field label="Title"><Input value={evaluator.title || ""} onChange={(event) => updateEvaluator({ ...evaluator, title: event.target.value })} /></Field>
        <Field label="Target stage"><Select value={evaluator.target_stage || ""} onChange={(event) => updateEvaluator({ ...evaluator, target_stage: event.target.value })}>{spec.stages.map((stage) => <option key={stage.id} value={stage.id}>{stage.title || stage.id}</option>)}</Select></Field>
        <Field label="Type"><Select value={evaluator.type} onChange={(event) => updateEvaluator({ ...evaluator, type: event.target.value as "llm_pairwise" | "human_pairwise" })}><option value="llm_pairwise">LLM pairwise</option><option value="human_pairwise">Human pairwise</option></Select></Field>
        {evaluator.type === "llm_pairwise" ? (
          <>
            <Field label="Judge model"><Input value={evaluator.model || ""} onChange={(event) => updateEvaluator({ ...evaluator, model: event.target.value })} /></Field>
            <Field label="Judge prompt"><Textarea className="h-32 font-mono text-xs" value={evaluator.prompt_inline || ""} onChange={(event) => updateEvaluator({ ...evaluator, prompt_inline: event.target.value, prompt_path: null })} /></Field>
          </>
        ) : null}
        <div className="grid grid-cols-2 gap-2">
          <Field label="Sample %"><Input value={String(evaluator.pairing?.sample_pct ?? 100)} onChange={(event) => updateEvaluator({ ...evaluator, pairing: { ...evaluator.pairing, sample_pct: Number(event.target.value) } })} /></Field>
          <Field label="Swap"><Select value={String(Boolean(evaluator.pairing?.swap))} onChange={(event) => updateEvaluator({ ...evaluator, pairing: { ...evaluator.pairing, swap: event.target.value === "true" } })}><option value="false">Off</option><option value="true">On</option></Select></Field>
        </div>
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return <label className="grid gap-1 text-xs font-bold text-ink-soft">{label}{children}</label>;
}
