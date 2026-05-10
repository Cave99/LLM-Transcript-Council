"""Tiny background-thread launcher for local run and analysis jobs."""

from __future__ import annotations

import asyncio
import threading
import traceback
from collections.abc import Callable

from sqlmodel import Session

from council.analysis import generate_judge_pattern_analysis
from council.graph_runtime import execute_graph_native_run
from council.models import ExperimentGraph, GraphRun, GraphStatus, Run, Status
from council.runner import execute_run

SessionFactory = Callable[[], Session]

RUN_THREADS: dict[int, threading.Thread] = {}
GRAPH_RUN_THREADS: dict[int, threading.Thread] = {}
ANALYSIS_THREADS: dict[int, threading.Thread] = {}


def start_run_thread(run_id: int, session_factory: SessionFactory) -> None:
    """Start a background run worker if one is not already active."""

    if _thread_is_running(RUN_THREADS, run_id):
        return

    def target() -> None:
        try:
            asyncio.run(execute_run(run_id, session_factory))
        except Exception as exc:
            with session_factory() as session:
                run = session.get(Run, run_id)
                if run:
                    run.status = Status.failed
                    run.error = str(exc)
                    session.add(run)
                    graph = session.get(ExperimentGraph, run.graph_id)
                    if graph:
                        graph.status = GraphStatus.failed
                        session.add(graph)
                    session.commit()

    _start_thread(RUN_THREADS, run_id, target)


def start_analysis_thread(run_id: int, session_factory: SessionFactory) -> None:
    """Start a judge-pattern analysis worker if one is not already active."""

    if _thread_is_running(ANALYSIS_THREADS, run_id):
        return

    def target() -> None:
        asyncio.run(generate_judge_pattern_analysis(run_id, session_factory))

    _start_thread(ANALYSIS_THREADS, run_id, target)


def start_graph_run_thread(graph_run_id: int, session_factory: SessionFactory) -> None:
    """Start a graph-native worker if one is not already active."""

    if _thread_is_running(GRAPH_RUN_THREADS, graph_run_id):
        return

    def target() -> None:
        try:
            asyncio.run(execute_graph_native_run(graph_run_id, session_factory))
        except Exception as exc:
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

    _start_thread(GRAPH_RUN_THREADS, graph_run_id, target)


def run_thread_is_active(run_id: int) -> bool:
    """Report whether a run worker is currently active."""

    return _thread_is_running(RUN_THREADS, run_id)


def _thread_is_running(threads: dict[int, threading.Thread], key: int) -> bool:
    """Keep duplicate worker checks consistent across job types."""

    return key in threads and threads[key].is_alive()


def _start_thread(threads: dict[int, threading.Thread], key: int, target) -> None:
    """Launch and remember one daemon worker thread."""

    thread = threading.Thread(target=target, daemon=True)
    threads[key] = thread
    thread.start()
