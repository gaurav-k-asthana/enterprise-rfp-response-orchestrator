"""Run only the exact manifest-locked provider recovery command."""

from rfp_orchestrator.provider_recovery_cli import main

if __name__ == "__main__":
    raise SystemExit(main())
