import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

CREDENTIAL_ENV_VARS = {
    "OPENAI_API_KEY",
    "OPENAI_MODEL",
    "PROVIDER_GRAPH_CALLS_ENABLED",
    "OPENAI_EMBEDDING_MODEL",
    "PINECONE_API_KEY",
    "PINECONE_INDEX",
    "PINECONE_NAMESPACE",
    "LANGSMITH_API_KEY",
    "LANGCHAIN_API_KEY",
    "LANGSMITH_ENDPOINT",
    "NEBIUS_API_KEY",
    "ELEVENLABS_API_KEY",
}


OFFLINE_PROBE = textwrap.dedent(
    """
    import json
    from pathlib import Path
    import socket
    import sys


    def network_disabled(*args, **kwargs):
        raise AssertionError("offline verification attempted an outbound network connection")


    class OfflineSocket(socket.socket):
        def connect(self, *args, **kwargs):
            network_disabled()

        def connect_ex(self, *args, **kwargs):
            network_disabled()


    socket.create_connection = network_disabled
    socket.socket = OfflineSocket

    assert "openai" not in sys.modules
    assert "pinecone" not in sys.modules

    from rfp_orchestrator.config import Settings
    from rfp_orchestrator.ingestion import build_ingestion_plan
    from rfp_orchestrator.models import Domain
    from rfp_orchestrator.pinecone_adapter import (
        PineconeNotConfiguredError,
        PineconeRetrieverAdapter,
    )
    from rfp_orchestrator.retrieval import RetrievalMethod, build_offline_retrievers

    settings = Settings(_env_file=None)
    assert settings.openai_api_key is None
    assert settings.openai_model is None
    assert settings.provider_graph_calls_enabled is False
    assert settings.openai_embedding_model is None
    assert settings.pinecone_api_key is None
    assert settings.pinecone_index is None
    assert settings.langsmith_api_key is None

    retrievers = build_offline_retrievers(Path("data/kb"))
    ingestion_plan = build_ingestion_plan(Path("data/kb"))
    product = retrievers.product.search("SAML SCIM", k=5)
    security = retrievers.security.search("TLS 1.3 encryption", k=5)
    implementation = retrievers.implementation.search("implementation onboarding timeline", k=5)

    assert product and all(item.domain is Domain.PRODUCT for item in product)
    assert security and all(item.domain is Domain.SECURITY for item in security)
    assert implementation and all(item.domain is Domain.IMPLEMENTATION for item in implementation)
    assert all(item.retrieval_method is RetrievalMethod.HYBRID for item in product)
    assert all(item.retrieval_method is RetrievalMethod.HYBRID for item in security)
    assert all(
        item.retrieval_method is RetrievalMethod.SEMANTIC_SUBSTITUTE
        for item in implementation
    )

    adapter = PineconeRetrieverAdapter(domain=Domain.PRODUCT, namespace="offline-check")
    try:
        adapter.search("SAML")
    except PineconeNotConfiguredError:
        pass
    else:
        raise AssertionError("unconfigured Pinecone search did not fail closed")

    assert adapter.is_initialized is False
    assert ingestion_plan.records
    assert ingestion_plan.public_manifest()["network_calls_made"] == 0
    assert "openai" not in sys.modules
    assert "pinecone" not in sys.modules

    print(
        json.dumps(
            {
                "implementation_results": len(implementation),
                "openai_loaded": "openai" in sys.modules,
                "pinecone_loaded": "pinecone" in sys.modules,
                "product_results": len(product),
                "security_results": len(security),
            }
        )
    )
    """
)


def _credential_free_environment() -> dict[str, str]:
    environment = os.environ.copy()
    for variable in CREDENTIAL_ENV_VARS:
        environment.pop(variable, None)
    environment["PYTHONPATH"] = str(PROJECT_ROOT / "src")
    return environment


def test_clean_process_imports_and_local_searches_work_without_credentials_or_network() -> None:
    result = subprocess.run(
        [sys.executable, "-c", OFFLINE_PROBE],
        cwd=PROJECT_ROOT,
        env=_credential_free_environment(),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    observed = json.loads(result.stdout)
    assert observed["product_results"] > 0
    assert observed["security_results"] > 0
    assert observed["implementation_results"] > 0
    assert observed["openai_loaded"] is False
    assert observed["pinecone_loaded"] is False


def test_example_environment_keeps_provider_credentials_blank() -> None:
    values = {
        key: value
        for key, value in (
            line.split("=", maxsplit=1)
            for line in (PROJECT_ROOT / ".env.example").read_text().splitlines()
            if line and not line.startswith("#") and "=" in line
        )
    }

    for variable in ("OPENAI_API_KEY", "PINECONE_API_KEY", "LANGSMITH_API_KEY"):
        assert values[variable] == ""
