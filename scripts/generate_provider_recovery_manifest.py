"""Generate the deterministic Step 4.G7 recovery manifest and review packet."""

from rfp_orchestrator.provider_recovery_manifest import (
    build_provider_recovery_manifest,
    write_provider_recovery_manifest,
)

if __name__ == "__main__":
    _, digest = write_provider_recovery_manifest(build_provider_recovery_manifest())
    print(digest)
