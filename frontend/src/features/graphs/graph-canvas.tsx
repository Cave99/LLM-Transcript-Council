import { useEffect, type ReactNode } from "react";
import ReactFlow, { Background, Controls, ReactFlowProvider, useNodesState, useReactFlow, type Connection, type Edge, type Node } from "reactflow";
import { Button } from "../../components/ui/button";
import type { GraphLayout, GraphSpec, NewNodeKind, StageSpec, CandidateSpec, EvaluatorSpec } from "./graph-spec-types";
import { newEvaluator, newStage, uniqueId } from "./graph-spec-types";
import { SemanticNode } from "./graph-node";
import type { SemanticEdgeDto, SemanticNodeDto } from "../../api/types";

const nodeTypes = { semantic: SemanticNode };

export function GraphCanvasProvider(props: GraphCanvasProps) {
  return (
    <ReactFlowProvider>
      <GraphCanvas {...props} />
    </ReactFlowProvider>
  );
}

type GraphCanvasProps = {
  spec: GraphSpec;
  nodes: SemanticNodeDto[];
  edges: SemanticEdgeDto[];
  layout: GraphLayout;
  selectedId: string;
  onSelect: (id: string) => void;
  onSpecChange: (spec: GraphSpec, layout?: GraphLayout) => void;
  onLayoutChange: (layout: GraphLayout) => void;
  inspector: ReactNode;
};

function GraphCanvas({ spec, nodes, edges, layout, onSelect, onSpecChange, onLayoutChange, inspector }: GraphCanvasProps) {
  const { screenToFlowPosition } = useReactFlow();
  const [flowNodes, setFlowNodes, onNodesChange] = useNodesState([]);

  useEffect(() => {
    setFlowNodes(nodes.map((node) => ({
      id: node.id,
      type: "semantic",
      position: layout[node.id] || { x: node.x, y: node.y },
      data: {},
      dragHandle: ".semantic-node-drag-handle",
      draggable: true,
    })));
  }, [nodes, layout, setFlowNodes]);

  const saveStage = (stageId: string, next: StageSpec) => onSpecChange({ ...spec, stages: spec.stages.map((item) => item.id === stageId ? next : item) });
  const saveEvaluator = (evaluatorId: string, next: EvaluatorSpec) => onSpecChange({ ...spec, evaluators: spec.evaluators.map((item) => item.id === evaluatorId ? next : item) });
  const saveCandidate = (stageId: string, candidateId: string, next: CandidateSpec) => {
    onSpecChange({
      ...spec,
      stages: spec.stages.map((stage) => stage.id === stageId ? { ...stage, candidates: stage.candidates.map((candidate) => candidate.id === candidateId ? next : candidate) } : stage),
    });
  };

  const semanticNodes: Node[] = nodes.map((node) => {
    const controlled = flowNodes.find((flowNode) => flowNode.id === node.id);
    return {
      id: node.id,
      type: "semantic",
      position: controlled?.position || layout[node.id] || { x: node.x, y: node.y },
      data: { node, spec, onSelect, onStageChange: saveStage, onCandidateChange: saveCandidate, onEvaluatorChange: saveEvaluator },
      dragHandle: ".semantic-node-drag-handle",
      draggable: true,
      selected: controlled?.selected,
      dragging: controlled?.dragging,
      width: controlled?.width,
      height: controlled?.height,
    };
  });
  const flowEdges: Edge[] = edges.map((edge) => ({ id: edge.id, source: edge.source, target: edge.target, animated: false }));

  const positionForNode = (nodeId: string) => {
    const controlled = flowNodes.find((node) => node.id === nodeId);
    const semantic = nodes.find((node) => node.id === nodeId);
    return controlled?.position || layout[nodeId] || (semantic ? { x: semantic.x, y: semantic.y } : undefined);
  };
  const positionRightOf = (sourceIds: string[], fallback = { x: 40, y: 160 }) => {
    const positions = sourceIds.map(positionForNode).filter((position): position is { x: number; y: number } => Boolean(position));
    if (!positions.length) return { x: fallback.x + 360, y: fallback.y };
    return {
      x: Math.round(Math.max(...positions.map((position) => position.x)) + 360),
      y: Math.round(positions.reduce((sum, position) => sum + position.y, 0) / positions.length),
    };
  };
  const createSemanticNode = (kind: NewNodeKind, position: { x: number; y: number }) => {
    const nodePosition = { x: Math.round(position.x), y: Math.round(position.y) };
    if (kind === "stage") {
      const id = uniqueId("stage", spec.stages.map((stage) => stage.id));
      onSpecChange({ ...spec, stages: [...spec.stages, newStage(id)] }, { ...layout, [id]: nodePosition });
      onSelect(id);
      return;
    }
    const id = uniqueId(kind === "human_pairwise" ? "human_review" : "judge", spec.evaluators.map((item) => item.id));
    onSpecChange({ ...spec, evaluators: [...spec.evaluators, newEvaluator(id, kind, spec.stages.at(-1)?.id || "")] }, { ...layout, [id]: nodePosition });
    onSelect(id);
  };
  const connectSemanticNodes = (connection: Connection) => {
    if (!connection.source || !connection.target || connection.source === connection.target) return;
    const sourceStage = spec.stages.find((stage) => stage.id === connection.source);
    const targetStage = spec.stages.find((stage) => stage.id === connection.target);
    const sourceEvaluator = spec.evaluators.find((evaluator) => evaluator.id === connection.source);
    const targetEvaluator = spec.evaluators.find((evaluator) => evaluator.id === connection.target);
    if (sourceStage && targetEvaluator) {
      onSpecChange({ ...spec, evaluators: spec.evaluators.map((item) => item.id === targetEvaluator.id ? { ...item, target_stage: sourceStage.id } : item) });
      return;
    }
    if (sourceEvaluator && targetStage) {
      onSpecChange({ ...spec, evaluators: spec.evaluators.map((item) => item.id === sourceEvaluator.id ? { ...item, target_stage: targetStage.id } : item) });
      return;
    }
    if (sourceStage && targetStage) {
      const withoutSource = spec.stages.filter((stage) => stage.id !== sourceStage.id);
      const targetIndex = withoutSource.findIndex((stage) => stage.id === targetStage.id);
      onSpecChange({ ...spec, stages: [...withoutSource.slice(0, targetIndex), sourceStage, ...withoutSource.slice(targetIndex)] });
    }
  };

  return (
    <section className="panel grid overflow-hidden lg:grid-cols-[minmax(0,1fr)_300px]">
      <div className="min-w-0">
        <div className="flex h-[57px] shrink-0 items-center justify-between gap-4 border-b border-line bg-surface-muted px-4">
          <div className="grid gap-0.5">
            <h2 className="text-sm font-bold">Semantic graph</h2>
            <p className="text-xs text-muted">Drag nodes to rearrange, connect outputs to reroute stages and judges.</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button type="button" variant="subtle" onClick={() => createSemanticNode("stage", positionRightOf(["dataset"]))}>Stage</Button>
            <Button type="button" variant="subtle" onClick={() => createSemanticNode("llm_pairwise", positionRightOf(["dataset"], { x: 40, y: 560 }))}>Judge</Button>
            <Button type="button" variant="subtle" onClick={() => createSemanticNode("human_pairwise", positionRightOf(["dataset"], { x: 40, y: 560 }))}>Review</Button>
          </div>
        </div>
        <div
          className="h-[72vh] min-h-[680px]"
          onDragOver={(event) => {
            event.preventDefault();
            event.dataTransfer.dropEffect = "copy";
          }}
          onDrop={(event) => {
            event.preventDefault();
            const kind = event.dataTransfer.getData("application/x-semantic-node-kind") as NewNodeKind;
            if (!kind) return;
            createSemanticNode(kind, screenToFlowPosition({ x: event.clientX, y: event.clientY }));
          }}
        >
          <ReactFlow
            nodes={semanticNodes}
            edges={flowEdges}
            nodeTypes={nodeTypes}
            fitView
            fitViewOptions={{ padding: 0.36 }}
            onNodesChange={onNodesChange}
            onNodeClick={(_, node) => onSelect(node.id)}
            onConnect={connectSemanticNodes}
            onNodeDragStop={(_, node) => onLayoutChange({ ...layout, [node.id]: { x: Math.round(node.position.x), y: Math.round(node.position.y) } })}
          >
            <Background />
            <Controls />
          </ReactFlow>
        </div>
      </div>
      <aside className="flex flex-col border-t border-line bg-surface lg:h-[calc(72vh+57px)] lg:min-h-[737px] lg:overflow-y-auto lg:border-l lg:border-t-0">
        {inspector}
      </aside>
    </section>
  );
}
