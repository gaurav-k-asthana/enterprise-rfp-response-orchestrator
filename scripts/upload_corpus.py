"""Run the separately approved, manifest-locked corpus upload."""

from rfp_orchestrator.ingestion_cli import upload_main

if __name__ == "__main__":
    raise SystemExit(upload_main())
