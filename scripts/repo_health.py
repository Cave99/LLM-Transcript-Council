#!/usr/bin/env python3
"""Run deterministic repository health checks for refactor risk."""

from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOTS = ("backend", "council", "tests", "scripts")
FRONTEND_ROOT = ROOT / "frontend" / "src"
EXCLUDED_PARTS = {".git", ".venv", "node_modules", "dist", "__pycache__", ".pytest_cache"}
STALE_PATTERNS = (
    "FastHTML",
    "fasthtml",
    "python-fasthtml",
    "legacy_graph_to_spec",
    "_legacy_rows",
    "GraphNode",
    "GraphEdge",
    "graph-editor",
    "/api/nodes",
    "/api/edges",
    "judge_prompt_node_id",
    "top_model_node_id",
    "model_node_id",
)


@dataclass(frozen=True)
class Finding:
    check: str
    path: str
    detail: str


class Complexity(ast.NodeVisitor):
    def __init__(self) -> None:
        self.score = 1

    def visit_If(self, node) -> None:  # noqa: N802
        self.score += 1
        self.generic_visit(node)

    def visit_For(self, node) -> None:  # noqa: N802
        self.score += 1
        self.generic_visit(node)

    def visit_AsyncFor(self, node) -> None:  # noqa: N802
        self.score += 1
        self.generic_visit(node)

    def visit_While(self, node) -> None:  # noqa: N802
        self.score += 1
        self.generic_visit(node)

    def visit_ExceptHandler(self, node) -> None:  # noqa: N802
        self.score += 1
        self.generic_visit(node)

    def visit_IfExp(self, node) -> None:  # noqa: N802
        self.score += 1
        self.generic_visit(node)

    def visit_BoolOp(self, node) -> None:  # noqa: N802
        self.score += max(0, len(node.values) - 1)
        self.generic_visit(node)

    def visit_comprehension(self, node) -> None:
        self.score += 1 + len(node.ifs)
        self.generic_visit(node)


def first_party_files(*suffixes: str) -> list[Path]:
    files: list[Path] = []
    for path in ROOT.rglob("*"):
        if any(part in EXCLUDED_PARTS for part in path.parts):
            continue
        if path.is_file() and path.suffix in suffixes:
            files.append(path)
    return sorted(files)


def python_complexity(max_complexity: int = 40, max_function_lines: int = 120) -> list[Finding]:
    findings: list[Finding] = []
    for root in PYTHON_ROOTS:
        for path in sorted((ROOT / root).rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    end = getattr(node, "end_lineno", node.lineno)
                    length = end - node.lineno + 1
                    visitor = Complexity()
                    visitor.visit(node)
                    rel = str(path.relative_to(ROOT))
                    if visitor.score > max_complexity:
                        findings.append(Finding("python_complexity", rel, f"{node.name} complexity {visitor.score} > {max_complexity} at line {node.lineno}"))
                    if length > max_function_lines:
                        findings.append(Finding("python_function_length", rel, f"{node.name} length {length} > {max_function_lines} at line {node.lineno}"))
    return findings


def file_size(max_python_lines: int = 760, max_frontend_lines: int = 360) -> list[Finding]:
    findings: list[Finding] = []
    for path in first_party_files(".py", ".ts", ".tsx"):
        rel = path.relative_to(ROOT)
        if rel.parts[0] not in {"backend", "council", "tests", "scripts", "frontend"}:
            continue
        line_count = len(path.read_text(encoding="utf-8").splitlines())
        if path.suffix == ".py" and line_count > max_python_lines:
            findings.append(Finding("python_file_length", str(rel), f"{line_count} lines > {max_python_lines}"))
        if path.suffix in {".ts", ".tsx"} and str(rel).startswith("frontend/src/") and line_count > max_frontend_lines:
            findings.append(Finding("frontend_file_length", str(rel), f"{line_count} lines > {max_frontend_lines}"))
    return findings


def frontend_state_signals(max_signals: int = 45) -> list[Finding]:
    findings: list[Finding] = []
    for path in sorted(FRONTEND_ROOT.rglob("*.tsx")):
        source = path.read_text(encoding="utf-8")
        signals = {
            "useState": source.count("useState("),
            "useEffect": source.count("useEffect("),
            "useMutation": source.count("useMutation("),
            "useQuery": source.count("useQuery("),
            "if": source.count("if ("),
            "map": source.count(".map("),
        }
        total = sum(signals.values())
        if total > max_signals:
            findings.append(Finding("frontend_state_signals", str(path.relative_to(ROOT)), f"{total} signals > {max_signals}: {signals}"))
    return findings


def stale_references() -> list[Finding]:
    findings: list[Finding] = []
    for path in first_party_files(".md", ".py", ".ts", ".tsx", ".toml", ".json"):
        rel = str(path.relative_to(ROOT))
        if rel.startswith(".impeccable/") or rel == "scripts/repo_health.py":
            continue
        source = path.read_text(encoding="utf-8", errors="ignore")
        for pattern in STALE_PATTERNS:
            if pattern in source:
                findings.append(Finding("stale_reference", rel, f"contains {pattern!r}"))
    return findings


def static_findings() -> list[Finding]:
    findings: list[Finding] = []
    findings.extend(python_complexity())
    findings.extend(file_size())
    findings.extend(frontend_state_signals())
    findings.extend(stale_references())
    return findings


def run_command(command: list[str]) -> int:
    completed = subprocess.run(command, cwd=ROOT, check=False)
    return completed.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print static findings as JSON.")
    parser.add_argument("--full", action="store_true", help="Also run pytest and the frontend production build.")
    args = parser.parse_args()

    findings = static_findings()
    if args.json:
        print(json.dumps([asdict(finding) for finding in findings], indent=2, sort_keys=True))
    elif findings:
        for finding in findings:
            print(f"{finding.check}: {finding.path}: {finding.detail}")
    else:
        print("Static repo health checks passed.")

    if findings:
        return 1
    if args.full:
        for command in (["uv", "run", "pytest"], ["pnpm", "--filter", "./frontend", "build"]):
            code = run_command(command)
            if code:
                return code
    return 0


if __name__ == "__main__":
    sys.exit(main())
