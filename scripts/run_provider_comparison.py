"""Run only the exact manifest-locked provider comparison command."""

from rfp_orchestrator.provider_execution_cli import main

if __name__ == "__main__":
    raise SystemExit(main())
