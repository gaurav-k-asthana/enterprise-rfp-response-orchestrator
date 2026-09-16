from rfp_orchestrator.node_status import initial_node_status
from rfp_orchestrator.sample_requirements import load_sample_requirements
from rfp_orchestrator.ui import (
    MAP_ERROR_MESSAGE,
    _render_architecture_frame,
    stream_sample_requirement,
)


class BrokenMapTarget:
    def __init__(self) -> None:
        self.warning_messages: list[tuple[str, str]] = []

    def iframe(self, _html: str, *, height: str) -> None:
        raise RuntimeError(f"private renderer detail at height {height}")

    def warning(self, message: str, *, icon: str) -> None:
        self.warning_messages.append((message, icon))


def test_frame_failure_becomes_a_sanitized_warning() -> None:
    target = BrokenMapTarget()

    rendered = _render_architecture_frame(target, initial_node_status())

    assert rendered is False
    assert target.warning_messages == [(MAP_ERROR_MESSAGE, "⚠️")]
    assert "private renderer detail" not in MAP_ERROR_MESSAGE


def test_callback_failure_does_not_interrupt_or_corrupt_the_graph_run() -> None:
    calls = 0

    def broken_callback(_status: dict, _edges: dict, _counts: dict, _event: dict) -> None:
        nonlocal calls
        calls += 1
        raise RuntimeError("simulated map renderer failure")

    result = stream_sample_requirement(
        load_sample_requirements()[0],
        1,
        "map-failure",
        on_event=broken_callback,
    )

    assert calls == 1
    assert result.visualization_failed is True
    assert result.state["final_status"] == "FINALIZED"
    assert result.state["final_answer"]
    assert result.node_status["commitment_promotion"] == "complete"
    assert result.event_count == len(result.state["execution_events"]) == 28


def test_failed_visualization_and_normal_run_produce_the_same_graph_result() -> None:
    def broken_callback(_status: dict, _edges: dict, _counts: dict, _event: dict) -> None:
        raise RuntimeError("simulated map renderer failure")

    requirement = load_sample_requirements()[0]
    failed_map = stream_sample_requirement(
        requirement,
        1,
        "failed-map-result",
        on_event=broken_callback,
    )
    normal = stream_sample_requirement(
        requirement,
        1,
        "normal-map-result",
    )

    stable_fields = (
        "requirement_id",
        "strategy",
        "selected_specialists",
        "final_status",
        "final_answer",
        "commitments",
    )
    assert {key: failed_map.state[key] for key in stable_fields} == {
        key: normal.state[key] for key in stable_fields
    }
    assert failed_map.visualization_failed is True
    assert normal.visualization_failed is False
