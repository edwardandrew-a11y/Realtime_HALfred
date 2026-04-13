#!/usr/bin/env python3
"""
Session log viewer for Realtime HALfred.

Reads JSONL session logs, groups events by trace_id, reconstructs causal
relationships from span_id / parent_span_id, and renders a readable tree view.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


VERBOSITY_LEVELS = ("summary", "detail", "full")

SUMMARY_EVENTS = {
    "session_start",
    "session_end",
    "user_transcript",
    "user_message",
    "assistant_text_complete",
    "agent_call",
    "agent_response",
    "error",
}

DETAIL_EVENTS = SUMMARY_EVENTS | {
    "llm_call",
    "llm_response",
    "reasoning_summary",
}


def _event_field(event: Dict[str, Any], key: str, default: Any = None) -> Any:
    if key in event:
        return event[key]
    data = event.get("data", {})
    if isinstance(data, dict) and key in data:
        return data[key]
    return default


def _preview(value: Any, limit: int = 120) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=True, default=str)
    else:
        text = str(value)
    text = text.replace("\n", " ").strip()
    if len(text) > limit:
        return text[: max(0, limit - 3)] + "..."
    return text


def _pretty_json(value: Any, indent: int = 2) -> str:
    try:
        return json.dumps(value, ensure_ascii=True, indent=indent, default=str, sort_keys=True)
    except Exception:
        return str(value)


def _parse_timestamp(entry: Dict[str, Any], fallback_index: int) -> float:
    ts = entry.get("timestamp")
    if isinstance(ts, (int, float)):
        return float(ts)
    return float(fallback_index)


def _format_timestamp(ts: float) -> str:
    if ts > 10_000_000:
        return time.strftime("%H:%M:%S", time.localtime(ts))
    return f"#{int(ts)}"


def _short_id(value: Any) -> str:
    text = str(value or "")
    return text[:8] if text else "-"


def _event_time(event: Dict[str, Any]) -> float:
    return _parse_timestamp(event, 0)


def _trace_title(trace: "TraceTree") -> str:
    events = trace.all_events()
    if not events:
        return f"TURN {trace.short_label}"
    ts = _format_timestamp(min(_event_time(event) for event in events))
    user_text = ""
    for event in sorted(events, key=_event_time):
        event_type = str(event.get("event_type", ""))
        data = event.get("data", {}) if isinstance(event.get("data"), dict) else {}
        if event_type == "user_transcript":
            user_text = _preview(data.get("content_text"), 120)
            break
        if event_type == "user_message":
            user_text = _preview(data.get("content_text"), 120)
            if user_text and user_text != "[Audio: 0 bytes]":
                break
    if user_text:
        return f"TURN {trace.short_label} @ {ts} | User: {user_text}"
    return f"TURN {trace.short_label} @ {ts}"


def _event_label(event: Dict[str, Any], verbosity: str) -> str:
    event_type = str(event.get("event_type", "unknown"))
    data = event.get("data", {}) if isinstance(event.get("data"), dict) else {}

    if event_type == "session_start":
        user_name = data.get("user_name", "unknown")
        mode = data.get("mode", "?")
        return f"Session started | user={user_name}, mode={mode}"
    if event_type == "session_end":
        duration = data.get("duration_seconds", "?")
        return f"Session ended | duration={duration:.1f}s" if isinstance(duration, (int, float)) else f"Session ended | duration={duration}"
    if event_type == "user_message":
        text = _preview(data.get("content_text"), 180)
        if text == "[Audio: 0 bytes]":
            return "User audio committed"
        return f"User message: {text}"
    if event_type == "user_transcript":
        return f"User said: {_preview(data.get('content_text'), 180)}"
    if event_type == "assistant_message":
        return f"Halfred message: {_preview(data.get('content'), 180)}"
    if event_type == "assistant_text_complete":
        return f"Halfred replied: {_preview(data.get('content'), 220)}"
    if event_type == "assistant_text_delta":
        return f"Halfred streamed: {_preview(data.get('delta'), 120)}"
    if event_type == "agent_call":
        source = data.get("source", "?")
        target = data.get("target", "?")
        request = _preview(data.get("request"), 180)
        return f"{source} -> {target}: {request}"
    if event_type == "agent_response":
        source = data.get("source", "?")
        target = data.get("target", "?")
        task_success = data.get("task_success", data.get("success", True))
        status = "OK" if task_success else "FAILED"
        preview_limit = 800 if not task_success else 220
        response = _preview(data.get("response"), preview_limit)
        return f"{source} -> {target} [{status}]: {response}"
    if event_type == "llm_call":
        agent = data.get("agent", "?")
        model = data.get("model", "?")
        tools = data.get("tools", [])
        tools_text = ",".join(tools[:4]) if isinstance(tools, list) else str(tools)
        suffix = f" +{len(tools) - 4} more" if isinstance(tools, list) and len(tools) > 4 else ""
        metadata = data.get("metadata", {}) or {}
        is_followup = (
            metadata.get("type") == "follow_up"   # anki_agent: explicit metadata flag
            or (metadata.get("round") or 0) > 1   # supervisor: round counter > 1; guards None
        )
        call_type = " (follow-up)" if is_followup else ""
        return f"{agent} asked {model}{call_type} | tools: {tools_text}{suffix}"
    if event_type == "llm_response":
        agent = data.get("agent", "?")
        model = data.get("model", "?")
        response = _preview(data.get("response_preview"), 120)
        if response:
            return f"{agent} got {model} response: {response}"
        tool_calls = data.get("tool_calls") or []
        if tool_calls:
            tool_names = ", ".join(str(call.get("name", "?")) for call in tool_calls[:4] if isinstance(call, dict))
            return f"{agent} got {model} tool request: {tool_names}"
        return f"{agent} got {model} response"
    if event_type == "reasoning_summary":
        agent = data.get("agent", "?")
        return f"{agent} reasoning summary: {_preview(data.get('summary'), 220)}"
    if event_type == "subagent_tool_dispatch":
        agent = data.get("agent", "?")
        tool_name = data.get("tool_name", "?")
        task_success = data.get("task_success", data.get("success", True))
        status = "OK" if task_success else "FAILED"
        return f"{agent} called {tool_name} [{status}] -> {_preview(data.get('result_preview'), 180)}"
    if event_type == "tool_start":
        tool_name = data.get("tool_name", "?")
        agent = data.get("agent_name", data.get("agent", "?"))
        return f"{agent} started tool {tool_name}"
    if event_type == "tool_end":
        tool_name = data.get("tool_name", "?")
        agent = data.get("agent_name", data.get("agent", "?"))
        task_success = data.get("task_success", data.get("success", True))
        status = "OK" if task_success else "FAILED"
        return f"{agent} finished tool {tool_name} [{status}] -> {_preview(data.get('output'), 180)}"
    if event_type == "error":
        return f"Error: {_preview(data.get('error'), 180)}"
    if verbosity == "summary":
        return event_type

    bits = [event_type]
    for key in ("agent", "source", "target", "tool_name"):
        if key in data:
            bits.append(f"{key}={data[key]}")
    return " ".join(bits)


def _event_details(event: Dict[str, Any], verbosity: str, show_ids: bool) -> str:
    if verbosity == "summary" or not show_ids:
        return ""

    data = event.get("data", {}) if isinstance(event.get("data"), dict) else {}
    if verbosity == "detail":
        keys = [
            "interaction_id",
            "span_id",
            "parent_span_id",
            "response_id",
            "round",
            "tool_call_id",
            "model",
            "success",
            "duration_ms",
        ]
        fields = []
        for key in keys:
            value = _event_field(event, key)
            if value is not None:
                fields.append(f"{key}={value}")
        if fields:
            return " | " + ", ".join(fields)
        return ""

    pretty = _pretty_json(event)
    return "\n" + "\n".join("    " + line for line in pretty.splitlines())


@dataclass
class LogNode:
    node_id: str
    trace_id: str
    parent_id: Optional[str]
    events: List[Dict[str, Any]] = field(default_factory=list)
    children: List[str] = field(default_factory=list)
    synthetic: bool = False

    @property
    def primary_event(self) -> Dict[str, Any]:
        return self.events[0] if self.events else {"event_type": "synthetic_scope", "timestamp": 0, "data": {}}

    @property
    def timestamp(self) -> float:
        if not self.events:
            return 0.0
        return min(_parse_timestamp(event, 0) for event in self.events)


class TraceTree:
    def __init__(self, trace_id: str, label_index: int):
        self.trace_id = trace_id
        self.label_index = label_index
        self.nodes: Dict[str, LogNode] = {}
        self.roots: List[str] = []
        self._synthetic_counter = 0

    @property
    def short_label(self) -> str:
        if self.trace_id.startswith("trace_"):
            return f"#{self.label_index}"
        return "SESSION"

    @property
    def first_timestamp(self) -> float:
        events = self.all_events()
        if not events:
            return 0.0
        return min(_event_time(event) for event in events)

    def add_event(self, event: Dict[str, Any], fallback_index: int) -> str:
        data = event.get("data", {}) if isinstance(event.get("data"), dict) else {}
        span_id = _event_field(event, "span_id")
        parent_id = _event_field(event, "parent_span_id")
        if not span_id:
            self._synthetic_counter += 1
            span_id = f"{self.trace_id}:synthetic:{fallback_index}:{self._synthetic_counter}"
        node = self.nodes.get(span_id)
        if node is None:
            node = LogNode(
                node_id=str(span_id),
                trace_id=self.trace_id,
                parent_id=str(parent_id) if parent_id else None,
                synthetic=False,
            )
            self.nodes[node.node_id] = node
        node.events.append(event)
        if parent_id and not node.parent_id:
            node.parent_id = str(parent_id)
        self._link_node(node.node_id)
        return node.node_id

    def _link_node(self, node_id: str) -> None:
        node = self.nodes[node_id]
        if node.parent_id:
            if node.parent_id not in self.nodes:
                self.nodes[node.parent_id] = LogNode(
                    node_id=node.parent_id,
                    trace_id=self.trace_id,
                    parent_id=None,
                    synthetic=True,
                )
                if node.parent_id not in self.roots:
                    self.roots.append(node.parent_id)
            parent = self.nodes[node.parent_id]
            if node_id not in parent.children:
                parent.children.append(node_id)
            if node_id in self.roots:
                self.roots.remove(node_id)
        else:
            if node_id not in self.roots:
                self.roots.append(node_id)
        self._attach_waiting_children(node_id)

    def _attach_waiting_children(self, parent_id: str) -> None:
        parent = self.nodes.get(parent_id)
        if parent is None:
            return
        for node_id, node in self.nodes.items():
            if node.parent_id == parent_id and node_id != parent_id:
                if node_id not in parent.children:
                    parent.children.append(node_id)
                if node_id in self.roots:
                    self.roots.remove(node_id)

    def iter_roots(self) -> Iterable[LogNode]:
        for node_id in sorted(self.roots, key=lambda nid: (self._sort_timestamp(nid), nid)):
            yield self.nodes[node_id]

    def iter_children(self, node: LogNode) -> Iterable[LogNode]:
        for child_id in sorted(node.children, key=lambda nid: (self._sort_timestamp(nid), nid)):
            yield self.nodes[child_id]

    def _sort_timestamp(self, node_id: str, seen: Optional[set[str]] = None) -> float:
        node = self.nodes[node_id]
        if node.events:
            return node.timestamp
        if not node.children:
            return node.timestamp
        if seen is None:
            seen = set()
        if node_id in seen:
            return node.timestamp
        seen.add(node_id)
        return min(self._sort_timestamp(child_id, seen) for child_id in node.children)

    def all_events(self) -> List[Dict[str, Any]]:
        events: List[Dict[str, Any]] = []
        for node in self.nodes.values():
            events.extend(node.events)
        return events


class LogViewer:
    def __init__(self, verbosity: str = "summary", show_ids: bool = False):
        if verbosity not in VERBOSITY_LEVELS:
            raise ValueError(f"verbosity must be one of {VERBOSITY_LEVELS}")
        self.verbosity = verbosity
        self.show_ids = show_ids
        self.traces: Dict[str, TraceTree] = {}
        self._printed_nodes: Dict[Tuple[str, str], int] = {}
        self._seen_lines = 0
        self._trace_printed_events: Dict[str, int] = {}
        self._trace_counter = 0

    def add_entry(self, entry: Dict[str, Any], fallback_index: int) -> Tuple[str, bool]:
        trace_id = _event_field(entry, "trace_id") or entry.get("session_id") or "ungrouped"
        trace_id = str(trace_id)
        trace = self.traces.get(trace_id)
        if trace is None:
            self._trace_counter += 1
            trace = TraceTree(trace_id, label_index=self._trace_counter)
            self.traces[trace_id] = trace
        node_id = trace.add_event(entry, fallback_index)
        current_events = sum(len(node.events) for node in trace.nodes.values())
        previous_events = self._trace_printed_events.get(trace_id, 0)
        self._trace_printed_events[trace_id] = current_events
        return trace_id, current_events > previous_events

    def render_new(self, trace_ids: Optional[Iterable[str]] = None) -> None:
        if trace_ids is None:
            sorted_traces = sorted(
                self.traces.items(),
                key=lambda item: (item[1].first_timestamp, item[0]),
            )
            turn_index = 0
            for _, trace in sorted_traces:
                if trace.trace_id.startswith("trace_"):
                    turn_index += 1
                    trace.label_index = turn_index
            trace_ids = [trace_id for trace_id, _ in sorted_traces]
        for trace_id in trace_ids:
            trace = self.traces.get(trace_id)
            if trace is None:
                continue
            self._render_trace(trace)

    def _render_trace(self, trace: TraceTree) -> None:
        if self.show_ids:
            print(f"{_trace_title(trace)} | trace_id={trace.trace_id}")
        else:
            print(_trace_title(trace))
        for root in trace.iter_roots():
            self._render_node(trace, root, depth=0)
        print("")

    def _should_render_event(self, event_type: str) -> bool:
        if self.verbosity == "full":
            return True
        if self.verbosity == "detail":
            return event_type in DETAIL_EVENTS
        return event_type in SUMMARY_EVENTS

    def _render_node(self, trace: TraceTree, node: LogNode, depth: int) -> None:
        key = (trace.trace_id, node.node_id)
        count = len(node.events)
        visible_events = [event for event in node.events if self._should_render_event(str(event.get("event_type", "unknown")))]
        should_print = self._printed_nodes.get(key) != count
        if node.synthetic:
            for child in trace.iter_children(node):
                self._render_node(trace, child, depth)
            return

        if should_print and visible_events:
            self._printed_nodes[key] = count

            event = visible_events[0]
            timestamp = _format_timestamp(_parse_timestamp(event, 0))
            label = _event_label(event, self.verbosity)
            indent = "  " * depth
            marker = "-" if depth == 0 else ">"
            print(f"{indent}{marker} {timestamp} {label}{_event_details(event, self.verbosity, self.show_ids)}")

            if self.verbosity == "full" and len(visible_events) > 1:
                for extra in visible_events[1:]:
                    extra_ts = _format_timestamp(_parse_timestamp(extra, 0))
                    extra_label = _event_label(extra, self.verbosity)
                    print(f"{indent}  + {extra_ts} {extra_label}{_event_details(extra, self.verbosity, self.show_ids)}")

        for child in trace.iter_children(node):
            self._render_node(trace, child, depth + 1)

    def load_file(self, path: Path) -> int:
        count = 0
        with path.open("r", encoding="utf-8") as handle:
            for index, line in enumerate(handle):
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(entry, dict):
                    continue
                self.add_entry(entry, index)
                count += 1
        self._seen_lines = count
        return count

    def tail_file(self, path: Path, interval: float = 0.5) -> None:
        offset = 0
        with path.open("r", encoding="utf-8") as handle:
            handle.seek(0, os.SEEK_END)
            offset = handle.tell()

        print(f"Following {path} (Ctrl+C to stop)")
        try:
            while True:
                current_size = path.stat().st_size
                if current_size < offset:
                    offset = 0

                changed_traces = set()
                with path.open("r", encoding="utf-8") as handle:
                    handle.seek(offset)
                    new_data = handle.read()
                    offset = handle.tell()
                if new_data:
                    for line in new_data.splitlines():
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            entry = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if not isinstance(entry, dict):
                            continue
                        trace_id, changed = self.add_entry(entry, self._seen_lines)
                        self._seen_lines += 1
                        if changed:
                            changed_traces.add(trace_id)
                    if changed_traces:
                        self.render_new(sorted(changed_traces))
                time.sleep(interval)
        except KeyboardInterrupt:
            return


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Render Realtime HALfred session JSONL logs.")
    parser.add_argument("path", type=Path, help="Path to a session JSONL file")
    parser.add_argument(
        "--follow",
        action="store_true",
        help="Tail the file and render appended events as they arrive",
    )
    parser.add_argument(
        "--level",
        choices=VERBOSITY_LEVELS,
        default="summary",
        help="Render detail level",
    )
    parser.add_argument(
        "--refresh-interval",
        type=float,
        default=0.5,
        help="Polling interval in seconds for --follow",
    )
    parser.add_argument(
        "--show-ids",
        action="store_true",
        help="Include trace/span identifiers and other correlation IDs",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    path = args.path
    if not path.exists():
        parser.error(f"file not found: {path}")

    viewer = LogViewer(verbosity=args.level, show_ids=args.show_ids)
    viewer.load_file(path)
    viewer.render_new()

    if args.follow:
        viewer.tail_file(path, interval=args.refresh_interval)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
