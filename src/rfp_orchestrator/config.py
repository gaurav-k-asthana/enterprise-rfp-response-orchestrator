from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from rfp_orchestrator.provider_config import RETRIEVAL_TOP_K


class Settings(BaseSettings):
    """Environment-backed configuration. Secrets are never stored in source code."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openai_api_key: str | None = Field(default=None, repr=False)
    openai_model: str | None = None
    provider_graph_calls_enabled: bool = False
    openai_embedding_model: str | None = None
    pinecone_api_key: str | None = Field(default=None, repr=False)
    pinecone_index: str | None = None
    pinecone_namespace: str | None = None
    langsmith_api_key: str | None = Field(default=None, repr=False)
    langsmith_tracing: bool = False
    langsmith_project: str = "enterprise-rfp-orchestrator"
    max_retrieval_retries: int = Field(default=2, ge=0, le=2)
    retrieval_top_k: int = Field(default=RETRIEVAL_TOP_K, ge=1, le=RETRIEVAL_TOP_K)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
