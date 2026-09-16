"""Generate the deterministic Step 4.G6 manifest and exact command review."""

from rfp_orchestrator.provider_execution_manifest import (
    build_provider_execution_manifest,
    exact_provider_command,
    write_provider_execution_manifest,
)


def main() -> int:
    manifest = build_provider_execution_manifest()
    _, digest = write_provider_execution_manifest(manifest)
    print(f"Manifest SHA-256: {digest}")
    print("Provider calls made: 0")
    print("Paid command approved: no")
    print("Exact command requiring separate approval:")
    print(exact_provider_command(digest))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
