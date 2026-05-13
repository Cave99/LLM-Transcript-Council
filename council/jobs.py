"""Tiny background-thread launcher for local graph jobs."""

from __future__ import annotations

import asyncio
import threading
import traceback
from collections.abc import Callable

from sqlmodel import Session

from council.analysis import generate_graph_run_judge_summary
from council.graph_runtime import execute_graph_native_run
from council.models import ExperimentGraph, GraphRun, GraphStatus, Status

SessionFactory = Callable[[], Session]

GRAPH_RUN_THREADS: dict[int, threading.Thread] = {}
GRAPH_ANALYSIS_THREADS: dict[tuple[int, int | None, str, str], threading.Thread] = {}


def start_graph_analysis_thread(
    graph_run_id: int,
    session_factory: SessionFactory,
    *,
    judge_prompt_node_id: int | None = None,
    leaderboard_view: str = "aggregate",
    top_entity_key: str = "",
) -> None:
    """Start a graph-run judge summary worker if one is not already active."""

    key = (graph_run_id, judge_prompt_node_id, leaderboard_view, top_entity_key)
    if _thread_is_running(GRAPH_ANALYSIS_THREADS, key):
        return

    def target() -> None:
        asyncio.run(
            generate_graph_run_judge_summary(
                graph_run_id,
                session_factory,
                judge_prompt_node_id=judge_prompt_node_id,
                leaderboard_view=leaderboard_view,
                top_entity_key=top_entity_key,
            )
        )

    _start_thread(GRAPH_ANALYSIS_THREADS, key, target)


def start_graph_run_thread(graph_run_id: int, session_factory: SessionFactory) -> None:
    """Start a graph-native worker if one is not already active."""

    if _thread_is_running(GRAPH_RUN_THREADS, graph_run_id):
        return

    def target() -> None:
        print(f"[graph run {graph_run_id}] Background worker thread starting.", flush=True)
        try:
            asyncio.run(execute_graph_native_run(graph_run_id, session_factory))
        except Exception as exc:
            print(f"[graph run {graph_run_id}] Background worker crashed.", flush=True)
            print("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)), flush=True)
            with session_factory() as session:
                run = session.get(GraphRun, graph_run_id)
                if run:
                    run.status = Status.failed
                    run.error = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
                    session.add(run)
                    graph = session.get(ExperimentGraph, run.graph_id)
                    if graph:
                        graph.status = GraphStatus.failed
                        session.add(graph)
                    session.commit()
        finally:
            print(f"[graph run {graph_run_id}] Background worker thread stopped.", flush=True)

    _start_thread(GRAPH_RUN_THREADS, graph_run_id, target)


def _thread_is_running(threads: dict[int, threading.Thread], key: int) -> bool:
    """Keep duplicate worker checks consistent across job types."""

    return key in threads and threads[key].is_alive()


def _start_thread(threads: dict[int, threading.Thread], key: int, target) -> None:
    """Launch and remember one daemon worker thread."""

    thread = threading.Thread(target=target, daemon=True)
    threads[key] = thread
    thread.start()
