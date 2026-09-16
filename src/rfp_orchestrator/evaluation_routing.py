"""Reviewed Step 4.3 initial routing labels for all evaluation cases."""

from __future__ import annotations

from collections import Counter

from pydantic import BaseModel, ConfigDict, Field, model_validator

from rfp_orchestrator.evaluation_schema import (
    EXPECTED_CASE_IDS,
    EvaluationCase,
    EvaluationDataset,
    load_evaluation_dataset,
)
from rfp_orchestrator.models import Domain, StrategyType

INITIAL_STRATEGY_TYPES = {
    StrategyType.SINGLE_SPECIALIST,
    StrategyType.PARALLEL_SPECIALISTS,
    StrategyType.IMMEDIATE_HITL,
}
DOMAIN_ORDER = (Domain.PRODUCT, Domain.SECURITY, Domain.IMPLEMENTATION)


class RoutingAssignment(BaseModel):
    """Expected initial classification and minimum safe route for one case."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    expected_domains: list[Domain]
    initial_strategy: StrategyType
    selected_specialists: list[Domain]
    routing_reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def route_is_coherent(self) -> RoutingAssignment:
        if self.initial_strategy not in INITIAL_STRATEGY_TYPES:
            raise ValueError("routing gold must describe an initial strategy")
        if self.expected_domains != sorted(
            self.expected_domains,
            key=DOMAIN_ORDER.index,
        ):
            raise ValueError("expected domains must follow canonical peer order")
        if len(self.expected_domains) != len(set(self.expected_domains)):
            raise ValueError("expected domains cannot contain duplicates")
        if len(self.selected_specialists) != len(set(self.selected_specialists)):
            raise ValueError("selected specialists cannot contain duplicates")
        if not self.routing_reason.strip():
            raise ValueError("routing reason cannot be blank")

        if self.initial_strategy is StrategyType.SINGLE_SPECIALIST:
            if len(self.expected_domains) != 1:
                raise ValueError("single-specialist routing requires exactly one domain")
            if self.selected_specialists != self.expected_domains:
                raise ValueError("single-specialist routing must select its expected domain")
        elif self.initial_strategy is StrategyType.PARALLEL_SPECIALISTS:
            if not 2 <= len(self.expected_domains) <= 3:
                raise ValueError("parallel routing requires two or three domains")
            if self.selected_specialists != self.expected_domains:
                raise ValueError("parallel routing must select all expected peer specialists")
        elif self.expected_domains or self.selected_specialists:
            raise ValueError("immediate HITL routing cannot select domains or specialists")
        return self


def _single(domain: Domain, reason: str) -> RoutingAssignment:
    return RoutingAssignment(
        expected_domains=[domain],
        initial_strategy=StrategyType.SINGLE_SPECIALIST,
        selected_specialists=[domain],
        routing_reason=reason,
    )


def _parallel(*domains: Domain, reason: str) -> RoutingAssignment:
    return RoutingAssignment(
        expected_domains=list(domains),
        initial_strategy=StrategyType.PARALLEL_SPECIALISTS,
        selected_specialists=list(domains),
        routing_reason=reason,
    )


def _hitl(reason: str) -> RoutingAssignment:
    return RoutingAssignment(
        expected_domains=[],
        initial_strategy=StrategyType.IMMEDIATE_HITL,
        selected_specialists=[],
        routing_reason=reason,
    )


ROUTING_ASSIGNMENTS: dict[str, RoutingAssignment] = {
    "EVAL-001": _single(Domain.PRODUCT, "Identity provisioning is a Product capability."),
    "EVAL-002": _parallel(
        Domain.PRODUCT,
        Domain.SECURITY,
        reason="Key availability is Product-scoped while encryption controls are Security-scoped.",
    ),
    "EVAL-003": _single(Domain.SECURITY, "Certification status belongs to Security/Compliance."),
    "EVAL-004": _single(
        Domain.IMPLEMENTATION,
        "Plans, prerequisites, and customer responsibilities are Implementation concerns.",
    ),
    "EVAL-005": _single(
        Domain.PRODUCT,
        "The initial evidence route is Product for the documented SLA position.",
    ),
    "EVAL-006": _single(
        Domain.PRODUCT,
        "Connector availability and roadmap status belong to Product.",
    ),
    "EVAL-007": _single(
        Domain.PRODUCT,
        "Supported deployment models and installation availability belong to Product.",
    ),
    "EVAL-008": _single(
        Domain.SECURITY,
        "Transport-security protocol versions belong to Security/Compliance.",
    ),
    "EVAL-009": _single(
        Domain.SECURITY,
        "Encryption in transit and at rest belongs to Security/Compliance.",
    ),
    "EVAL-010": _single(
        Domain.SECURITY,
        "Assurance reports and certifications belong to Security/Compliance.",
    ),
    "EVAL-011": _parallel(
        Domain.PRODUCT,
        Domain.SECURITY,
        reason="Offering eligibility is Product-scoped; content and backup residency are Security-scoped.",
    ),
    "EVAL-012": _parallel(
        Domain.PRODUCT,
        Domain.SECURITY,
        reason="Plan entitlement and residency controls require Product and Security peers.",
    ),
    "EVAL-013": _single(
        Domain.SECURITY,
        "Regional data-access controls and the requested exception belong to Security/Compliance.",
    ),
    "EVAL-014": _single(
        Domain.SECURITY,
        "Post-termination content retention belongs to Security/Compliance.",
    ),
    "EVAL-015": _single(
        Domain.SECURITY,
        "Content and backup deletion controls belong to Security/Compliance.",
    ),
    "EVAL-016": _single(
        Domain.IMPLEMENTATION,
        "Duration, start conditions, and dependencies belong to Implementation.",
    ),
    "EVAL-017": _single(
        Domain.IMPLEMENTATION,
        "Customer roles, access, data, and test resources belong to Implementation.",
    ),
    "EVAL-018": _single(
        Domain.PRODUCT,
        "Connector availability and tier boundaries belong to Product.",
    ),
    "EVAL-019": _single(
        Domain.IMPLEMENTATION,
        "Custom-integration scope, timeline, and approval belong to Implementation.",
    ),
    "EVAL-020": _parallel(
        Domain.PRODUCT,
        Domain.SECURITY,
        reason="Offering capabilities span Product while encryption controls require Security.",
    ),
    "EVAL-021": _single(
        Domain.SECURITY,
        "FedRAMP authorization status belongs to Security/Compliance before any recovery.",
    ),
    "EVAL-022": _single(
        Domain.PRODUCT,
        "Private-data-center package availability belongs to Product.",
    ),
    "EVAL-023": _hitl(
        "Discount and indemnity acceptance requires organizational authority before specialist work."
    ),
    "EVAL-024": _hitl(
        "The embedded operating instruction must stop before specialist selection."
    ),
}


EXPECTED_STRATEGY_COUNTS: dict[StrategyType, int] = {
    StrategyType.SINGLE_SPECIALIST: 18,
    StrategyType.PARALLEL_SPECIALISTS: 4,
    StrategyType.IMMEDIATE_HITL: 2,
}

EXPECTED_DOMAIN_COUNTS: dict[Domain, int] = {
    Domain.PRODUCT: 10,
    Domain.SECURITY: 12,
    Domain.IMPLEMENTATION: 4,
}


def apply_routing_labels(
    dataset: EvaluationDataset | None = None,
    assignments: dict[str, RoutingAssignment] | None = None,
) -> EvaluationDataset:
    """Populate only the three Step 4.3 routing fields."""

    source = dataset or load_evaluation_dataset()
    selected = assignments or ROUTING_ASSIGNMENTS
    if tuple(selected) != EXPECTED_CASE_IDS:
        raise ValueError("routing assignments must contain EVAL-001 through EVAL-024 in order")

    cases: list[EvaluationCase] = []
    for case in source.cases:
        assignment = selected[case.case_id]
        payload = case.model_dump(mode="json")
        labels = payload["gold_labels"]
        labels["expected_domains"] = [item.value for item in assignment.expected_domains]
        labels["expected_strategy_family"] = assignment.initial_strategy.value
        labels["expected_specialists"] = [
            item.value for item in assignment.selected_specialists
        ]
        cases.append(EvaluationCase.model_validate(payload))

    payload = source.model_dump(mode="json")
    payload["cases"] = [case.model_dump(mode="json") for case in cases]
    routed = EvaluationDataset.model_validate(payload)
    validate_routing_labels(routed, selected)
    return routed


def strategy_counts(dataset: EvaluationDataset) -> dict[StrategyType, int]:
    counts = Counter(
        case.gold_labels.expected_strategy_family for case in dataset.cases
    )
    return {strategy: counts[strategy] for strategy in EXPECTED_STRATEGY_COUNTS}


def domain_counts(dataset: EvaluationDataset) -> dict[Domain, int]:
    counts = Counter(
        domain
        for case in dataset.cases
        for domain in case.gold_labels.expected_domains
    )
    return {domain: counts[domain] for domain in DOMAIN_ORDER}


def validate_routing_labels(
    dataset: EvaluationDataset,
    assignments: dict[str, RoutingAssignment] | None = None,
) -> None:
    """Reject missing, changed, non-peer, or internally inconsistent routing gold."""

    selected = assignments or ROUTING_ASSIGNMENTS
    if tuple(selected) != EXPECTED_CASE_IDS:
        raise ValueError("routing assignments must contain EVAL-001 through EVAL-024 in order")
    for case in dataset.cases:
        assignment = selected[case.case_id]
        labels = case.gold_labels
        if labels.expected_domains != assignment.expected_domains:
            raise ValueError(f"expected-domain drift for {case.case_id}")
        if labels.expected_strategy_family is not assignment.initial_strategy:
            raise ValueError(f"initial-strategy drift for {case.case_id}")
        if labels.expected_specialists != assignment.selected_specialists:
            raise ValueError(f"selected-specialist drift for {case.case_id}")

    if strategy_counts(dataset) != EXPECTED_STRATEGY_COUNTS:
        raise ValueError("initial-strategy distribution drift")
    if domain_counts(dataset) != EXPECTED_DOMAIN_COUNTS:
        raise ValueError("expected-domain distribution drift")


def render_routing_matrix(dataset: EvaluationDataset) -> str:
    """Render the initial routing gold as a human-reviewable Markdown table."""

    validate_routing_labels(dataset)
    strategies = strategy_counts(dataset)
    domains = domain_counts(dataset)
    lines = [
        "# Evaluation Routing Matrix — V1 Draft",
        "",
        (
            "This Step 4.3 artifact labels the initial decision immediately after "
            "requirement analysis. Later recovery, conflict, risk, HITL, and finalization "
            "transitions are not encoded as the initial strategy."
        ),
        "",
        "## Distribution",
        "",
        "| Initial strategy | Cases |",
        "|---|---:|",
    ]
    for strategy, count in strategies.items():
        lines.append(f"| {strategy.value.replace('_', ' ').title()} | {count} |")
    lines.extend(
        [
            "",
            "| Expected domain / selected peer | Case memberships |",
            "|---|---:|",
        ]
    )
    for domain, count in domains.items():
        label = "Security/Compliance" if domain is Domain.SECURITY else domain.value.title()
        lines.append(f"| {label} | {count} |")
    lines.extend(
        [
            "",
            (
                "Domain memberships total 26 because four cross-domain cases each select "
                "two peers. Immediate-HITL cases select no specialist."
            ),
            "",
            "## Case matrix",
            "",
            "| Case | Requirement | Expected domains | Initial strategy | Selected peer specialists | Why |",
            "|---|---|---|---|---|---|",
        ]
    )
    for case in dataset.cases:
        assignment = ROUTING_ASSIGNMENTS[case.case_id]
        domains_text = _domain_text(assignment.expected_domains)
        specialists_text = _domain_text(assignment.selected_specialists)
        strategy_text = assignment.initial_strategy.value.replace("_", " ").title()
        lines.append(
            f"| {case.case_id} | {case.requirement_id} | {domains_text} | "
            f"{strategy_text} | {specialists_text} | {assignment.routing_reason} |"
        )
    lines.extend(
        [
            "",
            "## Locked interpretation",
            "",
            "- Specialists are peers selected by the orchestrator.",
            "- Parallel selection does not create specialist-to-specialist edges.",
            "- The initial strategy is not a prediction of the complete execution trace.",
            "- These draft labels become frozen only after the Step 4.7 review checkpoint.",
            "",
        ]
    )
    return "\n".join(lines)


def _domain_text(domains: list[Domain]) -> str:
    if not domains:
        return "None"
    return ", ".join(
        "Security/Compliance" if domain is Domain.SECURITY else domain.value.title()
        for domain in domains
    )
