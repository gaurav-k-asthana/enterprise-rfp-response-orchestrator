"""Privacy-preserving LangSmith client and tracer controls."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from langchain_core.tracers.langchain import LangChainTracer

SANITIZED_TRACE_ERROR = "Trace execution failed; error details were redacted"


class SanitizedTraceError(RuntimeError):
    """Fixed error used at the external trace boundary."""


def sanitized_trace_error() -> SanitizedTraceError:
    """Return a new fixed-message error without inspecting the original exception."""

    return SanitizedTraceError(SANITIZED_TRACE_ERROR)


class PrivacyPreservingLangChainTracer(LangChainTracer):
    """Replace exception details before LangSmith serializes errored runs."""

    def on_chain_error(
        self,
        error: BaseException,
        *,
        inputs: dict[str, Any] | None = None,
        run_id: UUID,
        **kwargs: Any,
    ) -> Any:
        del error
        return super().on_chain_error(
            sanitized_trace_error(),
            inputs=None,
            run_id=run_id,
            **kwargs,
        )

    def on_tool_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> Any:
        del error
        return super().on_tool_error(
            sanitized_trace_error(),
            run_id=run_id,
            **kwargs,
        )

    def on_llm_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> Any:
        del error
        kwargs.pop("response", None)
        return super().on_llm_error(
            sanitized_trace_error(),
            run_id=run_id,
            **kwargs,
        )

    def on_retriever_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> Any:
        del error
        return super().on_retriever_error(
            sanitized_trace_error(),
            run_id=run_id,
            **kwargs,
        )


LANGSMITH_CLIENT_PRIVACY_OPTIONS: dict[str, bool] = {
    "hide_inputs": True,
    "hide_outputs": True,
    "omit_traced_runtime_info": True,
}
