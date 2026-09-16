"""Explicit, local-only faults for retrieval and specialist-output verification.

Faults are inert until a caller deliberately wraps a retriever bundle or the
offline specialist functions. They are not read from environment variables and
are not enabled by Streamlit or the normal graph builders.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from pydantic import ValidationError

from rfp_orchestrator.models import Domain, Requirement
from rfp_orchestrator.retrieval import (
    EvidenceChunk,
    OfflineSpecialistRetrievers,
    SearchFilters,
    SpecialistRetriever,
    enforce_top_k,
    tokenize_terms,
)
from rfp_orchestrator.specialists import (
    SpecialistNodeResult,
    implementation_specialist_node,
    product_specialist_node,
    security_specialist_node,
)


@dataclass(frozen=True)
class EmptyRetrievalReceipt:
    """Secret-free proof that one controlled empty result was returned."""

    fault_type: str
    domain: Domain
    invocation_number: int
    requested_top_k: int
    returned_count: int = 0


class EmptyRetrievalFault:
    """Deterministically replace selected domain-retrieval calls with empty lists."""

    fault_type = "empty_retrieval"

    def __init__(
        self,
        *,
        target_domain: Domain,
        empty_on_calls: tuple[int, ...] | None = None,
    ) -> None:
        if not isinstance(target_domain, Domain):
            raise TypeError("target_domain must be a Domain")
        if empty_on_calls is not None and (
            not isinstance(empty_on_calls, tuple)
            or not empty_on_calls
            or any(
                not isinstance(call, int) or isinstance(call, bool) or call < 1
                for call in empty_on_calls
            )
            or len(set(empty_on_calls)) != len(empty_on_calls)
        ):
            raise ValueError("empty_on_calls must contain distinct positive call numbers")
        self._target_domain = target_domain
        self._empty_on_calls = (
            None if empty_on_calls is None else frozenset(empty_on_calls)
        )
        self._invocation_count = 0
        self._receipts: list[EmptyRetrievalReceipt] = []

    @property
    def target_domain(self) -> Domain:
        return self._target_domain

    @property
    def invocation_count(self) -> int:
        return self._invocation_count

    @property
    def receipts(self) -> tuple[EmptyRetrievalReceipt, ...]:
        return tuple(self._receipts)

    def _should_return_empty(self, *, requested_top_k: int) -> bool:
        self._invocation_count += 1
        if (
            self._empty_on_calls is not None
            and self._invocation_count not in self._empty_on_calls
        ):
            return False
        self._receipts.append(
            EmptyRetrievalReceipt(
                fault_type=self.fault_type,
                domain=self.target_domain,
                invocation_number=self.invocation_count,
                requested_top_k=requested_top_k,
            )
        )
        return True

    def wrap(
        self,
        retrievers: OfflineSpecialistRetrievers,
    ) -> OfflineSpecialistRetrievers:
        """Return a new bundle with only the selected domain faulted."""

        wrapped = {
            Domain.PRODUCT: retrievers.product,
            Domain.SECURITY: retrievers.security,
            Domain.IMPLEMENTATION: retrievers.implementation,
        }
        target = wrapped[self.target_domain]
        if target.domain is not self.target_domain:
            raise ValueError("target retriever domain does not match its bundle position")
        wrapped[self.target_domain] = EmptyRetrievalFaultRetriever(target, fault=self)
        return OfflineSpecialistRetrievers(
            product=wrapped[Domain.PRODUCT],
            security=wrapped[Domain.SECURITY],
            implementation=wrapped[Domain.IMPLEMENTATION],
        )


class EmptyRetrievalFaultRetriever:
    """Retriever-compatible boundary that returns an observable empty result."""

    def __init__(
        self,
        wrapped: SpecialistRetriever,
        *,
        fault: EmptyRetrievalFault,
    ) -> None:
        if wrapped.domain is not fault.target_domain:
            raise ValueError("fault target must match the wrapped retriever domain")
        self._wrapped = wrapped
        self._fault = fault

    @property
    def domain(self) -> Domain:
        return self._wrapped.domain

    @property
    def chunk_count(self) -> int:
        return self._wrapped.chunk_count

    def search(
        self,
        query: str,
        *,
        k: int = 5,
        filters: SearchFilters | None = None,
    ) -> list[EvidenceChunk]:
        """Validate the normal contract and return empty only on selected calls."""

        limit = enforce_top_k(k)
        if not tokenize_terms(query):
            raise ValueError("retrieval query must contain at least one searchable token")
        if self._fault._should_return_empty(requested_top_k=limit):
            return []
        return self._wrapped.search(query, k=limit, filters=filters)


class InjectedToolException(RuntimeError):
    """Fixed, content-free exception raised only by an opted-in test fault."""


@dataclass(frozen=True)
class ToolExceptionReceipt:
    """Safe record of one deliberately failed retriever invocation."""

    fault_type: str
    domain: Domain
    invocation_number: int
    requested_top_k: int
    error_code: str


class ToolExceptionFault:
    """Raise a controlled tool error on selected calls to one domain retriever."""

    fault_type = "tool_exception"
    error_code = "INJECTED_RETRIEVAL_TOOL_EXCEPTION"

    def __init__(
        self,
        *,
        target_domain: Domain,
        fail_on_calls: tuple[int, ...] = (1,),
    ) -> None:
        if not isinstance(target_domain, Domain):
            raise TypeError("target_domain must be a Domain")
        if (
            not isinstance(fail_on_calls, tuple)
            or not fail_on_calls
            or any(
                not isinstance(call, int) or isinstance(call, bool) or call < 1
                for call in fail_on_calls
            )
            or len(set(fail_on_calls)) != len(fail_on_calls)
        ):
            raise ValueError("fail_on_calls must contain distinct positive call numbers")
        self._target_domain = target_domain
        self._fail_on_calls = frozenset(fail_on_calls)
        self._invocation_count = 0
        self._receipts: list[ToolExceptionReceipt] = []

    @property
    def target_domain(self) -> Domain:
        return self._target_domain

    @property
    def invocation_count(self) -> int:
        return self._invocation_count

    @property
    def receipts(self) -> tuple[ToolExceptionReceipt, ...]:
        return tuple(self._receipts)

    def wrap(
        self,
        retrievers: OfflineSpecialistRetrievers,
    ) -> OfflineSpecialistRetrievers:
        """Return a new bundle; do not mutate the original or other domains."""

        wrapped = {
            Domain.PRODUCT: retrievers.product,
            Domain.SECURITY: retrievers.security,
            Domain.IMPLEMENTATION: retrievers.implementation,
        }
        target = wrapped[self.target_domain]
        if target.domain is not self.target_domain:
            raise ValueError("target retriever domain does not match its bundle position")
        wrapped[self.target_domain] = ToolExceptionFaultRetriever(target, fault=self)
        return OfflineSpecialistRetrievers(
            product=wrapped[Domain.PRODUCT],
            security=wrapped[Domain.SECURITY],
            implementation=wrapped[Domain.IMPLEMENTATION],
        )

    def _should_fail(self, *, requested_top_k: int) -> bool:
        self._invocation_count += 1
        if self._invocation_count not in self._fail_on_calls:
            return False
        self._receipts.append(
            ToolExceptionReceipt(
                fault_type=self.fault_type,
                domain=self.target_domain,
                invocation_number=self._invocation_count,
                requested_top_k=requested_top_k,
                error_code=self.error_code,
            )
        )
        return True


class ToolExceptionFaultRetriever:
    """Retriever-compatible wrapper with a deterministic exception switch."""

    def __init__(
        self,
        wrapped: SpecialistRetriever,
        *,
        fault: ToolExceptionFault,
    ) -> None:
        if wrapped.domain is not fault.target_domain:
            raise ValueError("fault target must match the wrapped retriever domain")
        self._wrapped = wrapped
        self._fault = fault

    @property
    def domain(self) -> Domain:
        return self._wrapped.domain

    @property
    def chunk_count(self) -> int:
        return self._wrapped.chunk_count

    def search(
        self,
        query: str,
        *,
        k: int = 5,
        filters: SearchFilters | None = None,
    ) -> list[EvidenceChunk]:
        limit = enforce_top_k(k)
        if not tokenize_terms(query):
            raise ValueError("retrieval query must contain at least one searchable token")
        if self._fault._should_fail(requested_top_k=limit):
            raise InjectedToolException("Controlled retrieval tool failure (test only).")
        return self._wrapped.search(query, k=limit, filters=filters)


class InjectedStructuredOutputError(RuntimeError):
    """Fixed, content-free signal for a rejected synthetic specialist payload."""


@dataclass(frozen=True)
class InvalidStructuredOutputReceipt:
    """Safe proof that the real specialist-output schema rejected the fault."""

    fault_type: str
    domain: Domain
    invocation_number: int
    error_code: str


OfflineSpecialistFunction = Callable[..., SpecialistNodeResult]


class InvalidStructuredOutputFault:
    """Inject a synthetic invalid payload after one offline specialist runs."""

    fault_type = "invalid_structured_output"
    error_code = "INVALID_SPECIALIST_OUTPUT_REJECTED"

    def __init__(
        self,
        *,
        target_domain: Domain,
        fail_on_calls: tuple[int, ...] = (1,),
    ) -> None:
        if not isinstance(target_domain, Domain):
            raise TypeError("target_domain must be a Domain")
        if (
            not isinstance(fail_on_calls, tuple)
            or not fail_on_calls
            or any(
                not isinstance(call, int) or isinstance(call, bool) or call < 1
                for call in fail_on_calls
            )
            or len(set(fail_on_calls)) != len(fail_on_calls)
        ):
            raise ValueError("fail_on_calls must contain distinct positive call numbers")
        self._target_domain = target_domain
        self._fail_on_calls = frozenset(fail_on_calls)
        self._invocation_count = 0
        self._receipts: list[InvalidStructuredOutputReceipt] = []

    @property
    def target_domain(self) -> Domain:
        return self._target_domain

    @property
    def invocation_count(self) -> int:
        return self._invocation_count

    @property
    def receipts(self) -> tuple[InvalidStructuredOutputReceipt, ...]:
        return tuple(self._receipts)

    def wrap_offline_specialists(self) -> dict[Domain, OfflineSpecialistFunction]:
        """Replace one function in a fresh, offline-only peer-specialist map."""

        functions: dict[Domain, OfflineSpecialistFunction] = {
            Domain.PRODUCT: product_specialist_node,
            Domain.SECURITY: security_specialist_node,
            Domain.IMPLEMENTATION: implementation_specialist_node,
        }
        normal = functions[self.target_domain]

        def injected(
            requirement: Requirement,
            retriever: SpecialistRetriever,
            *,
            query_override: str | None = None,
        ) -> SpecialistNodeResult:
            # Let the real offline specialist enforce its domain/prompt boundary.
            result = normal(requirement, retriever, query_override=query_override)
            self._invocation_count += 1
            if self._invocation_count not in self._fail_on_calls:
                return result

            # Deliberately validate only static synthetic content. A Pydantic
            # error for the actual answer could include raw text in its repr.
            malformed = {
                "output": {
                    "specialist": self.target_domain.value,
                    "claims": [],
                    "proposed_answer": "Synthetic test payload.",
                    "support_status": "NOT_A_SUPPORT_STATUS",
                },
                "evidence": [],
            }
            try:
                SpecialistNodeResult.model_validate(malformed)
            except ValidationError:
                self._receipts.append(
                    InvalidStructuredOutputReceipt(
                        fault_type=self.fault_type,
                        domain=self.target_domain,
                        invocation_number=self._invocation_count,
                        error_code=self.error_code,
                    )
                )
                raise InjectedStructuredOutputError(
                    "Controlled specialist output validation failure (test only)."
                ) from None
            raise AssertionError("synthetic invalid specialist output passed validation")

        functions[self.target_domain] = injected
        return functions


class InjectedTimeoutError(TimeoutError):
    """Fixed, content-free signal for a simulated retriever deadline breach."""


@dataclass(frozen=True)
class TimeoutFaultReceipt:
    """Safe record of one virtual, deliberately timed-out retriever call."""

    fault_type: str
    domain: Domain
    invocation_number: int
    requested_top_k: int
    timeout_ms: int
    simulated_elapsed_ms: int
    error_code: str


class TimeoutFault:
    """Simulate a domain retriever exceeding a deadline without real waiting."""

    fault_type = "timeout"
    error_code = "INJECTED_RETRIEVAL_TIMEOUT"

    def __init__(
        self,
        *,
        target_domain: Domain,
        timeout_ms: int = 100,
        simulated_elapsed_ms: int = 101,
        fail_on_calls: tuple[int, ...] = (1,),
    ) -> None:
        if not isinstance(target_domain, Domain):
            raise TypeError("target_domain must be a Domain")
        if not isinstance(timeout_ms, int) or isinstance(timeout_ms, bool) or timeout_ms < 1:
            raise ValueError("timeout_ms must be a positive integer")
        if (
            not isinstance(simulated_elapsed_ms, int)
            or isinstance(simulated_elapsed_ms, bool)
            or simulated_elapsed_ms < 0
        ):
            raise ValueError("simulated_elapsed_ms must be a nonnegative integer")
        if (
            not isinstance(fail_on_calls, tuple)
            or not fail_on_calls
            or any(
                not isinstance(call, int) or isinstance(call, bool) or call < 1
                for call in fail_on_calls
            )
            or len(set(fail_on_calls)) != len(fail_on_calls)
        ):
            raise ValueError("fail_on_calls must contain distinct positive call numbers")
        self._target_domain = target_domain
        self._timeout_ms = timeout_ms
        self._simulated_elapsed_ms = simulated_elapsed_ms
        self._fail_on_calls = frozenset(fail_on_calls)
        self._invocation_count = 0
        self._receipts: list[TimeoutFaultReceipt] = []

    @property
    def target_domain(self) -> Domain:
        return self._target_domain

    @property
    def invocation_count(self) -> int:
        return self._invocation_count

    @property
    def receipts(self) -> tuple[TimeoutFaultReceipt, ...]:
        return tuple(self._receipts)

    def wrap(
        self,
        retrievers: OfflineSpecialistRetrievers,
    ) -> OfflineSpecialistRetrievers:
        """Return a new bundle with only the selected domain deadline-wrapped."""

        wrapped = {
            Domain.PRODUCT: retrievers.product,
            Domain.SECURITY: retrievers.security,
            Domain.IMPLEMENTATION: retrievers.implementation,
        }
        target = wrapped[self.target_domain]
        if target.domain is not self.target_domain:
            raise ValueError("target retriever domain does not match its bundle position")
        wrapped[self.target_domain] = TimeoutFaultRetriever(target, fault=self)
        return OfflineSpecialistRetrievers(
            product=wrapped[Domain.PRODUCT],
            security=wrapped[Domain.SECURITY],
            implementation=wrapped[Domain.IMPLEMENTATION],
        )

    def _deadline_exceeded(self, *, requested_top_k: int) -> bool:
        self._invocation_count += 1
        if (
            self._invocation_count not in self._fail_on_calls
            or self._simulated_elapsed_ms < self._timeout_ms
        ):
            return False
        self._receipts.append(
            TimeoutFaultReceipt(
                fault_type=self.fault_type,
                domain=self.target_domain,
                invocation_number=self._invocation_count,
                requested_top_k=requested_top_k,
                timeout_ms=self._timeout_ms,
                simulated_elapsed_ms=self._simulated_elapsed_ms,
                error_code=self.error_code,
            )
        )
        return True


class TimeoutFaultRetriever:
    """Retriever-compatible wrapper that applies one deterministic virtual deadline."""

    def __init__(
        self,
        wrapped: SpecialistRetriever,
        *,
        fault: TimeoutFault,
    ) -> None:
        if wrapped.domain is not fault.target_domain:
            raise ValueError("fault target must match the wrapped retriever domain")
        self._wrapped = wrapped
        self._fault = fault

    @property
    def domain(self) -> Domain:
        return self._wrapped.domain

    @property
    def chunk_count(self) -> int:
        return self._wrapped.chunk_count

    def search(
        self,
        query: str,
        *,
        k: int = 5,
        filters: SearchFilters | None = None,
    ) -> list[EvidenceChunk]:
        limit = enforce_top_k(k)
        if not tokenize_terms(query):
            raise ValueError("retrieval query must contain at least one searchable token")
        if self._fault._deadline_exceeded(requested_top_k=limit):
            raise InjectedTimeoutError("Controlled retrieval timeout (test only).")
        return self._wrapped.search(query, k=limit, filters=filters)
