"""Generate the offline Step 4.G8 final provider evaluation review artifacts."""

from rfp_orchestrator.provider_final_evaluation import (
    build_provider_final_evaluation,
    write_provider_final_evaluation,
)


def main() -> int:
    report = build_provider_final_evaluation()
    json_digest, markdown_digest = write_provider_final_evaluation(report)
    print(f"Primary cases: {report.primary_case_count}")
    print(f"Preserved executions: {report.total_requested_architecture_executions}")
    print(f"Successful executions: {report.total_successful_executions}")
    print(f"Failed executions: {report.total_failed_executions}")
    print(f"Bounded preference: {report.bounded_preference}")
    print(f"JSON SHA-256: {json_digest}")
    print(f"Markdown SHA-256: {markdown_digest}")
    print("New provider calls made: 0")
    print("Phase 4 exit gate: awaiting human review")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
