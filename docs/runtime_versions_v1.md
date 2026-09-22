# V1 runtime and direct dependency versions

This is the **Step 5.15 local environment snapshot** for the reviewed RFP
prototype on September 16, 2026. The project virtual environment reported
Python **3.10.11**, macOS/Darwin **27.0.0**, and **arm64**. The existing
`pyproject.toml` declares Python `>=3.10` and minimum package versions; it
does not by itself select the exact versions below.

| Role | Direct distribution | Installed version |
|---|---|---:|
| Runtime | `langchain` | 1.3.18 |
| Runtime | `langgraph` | 1.2.11 |
| Runtime | `langsmith` | 0.11.2 |
| Runtime | `openai` | 3.6.0 |
| Runtime | `pinecone` | 9.1.0 |
| Runtime | `streamlit` | 1.62.0 |
| Runtime | `python-docx` | 1.2.0 |
| Runtime | `pydantic-settings` | 2.15.0 |
| Development | `pytest` | 9.1.1 |
| Development | `ruff` | 0.16.5 |
| Development | `mypy` | 2.3.1 |

The exact direct versions are also in
[`constraints-direct-v1.txt`](../constraints-direct-v1.txt). For a **new**
virtual environment, this command asks pip to use those direct versions:

```bash
python -m pip install -c constraints-direct-v1.txt -e '.[dev]'
```

That installation may access the package index; it was **not run** for this
snapshot. It does not call OpenAI, Pinecone, or LangSmith. Do not run it in
the already-working `.venv` merely to inspect versions. In an activated
environment, use `python --version` and `python -m pip check` for a basic
runtime check. Step 5.17 completed that check on September 22, 2026: 1,309
tests passed, Ruff and `pip check` passed, the saved evaluation reports
regenerated deterministically, and a fresh local Streamlit server returned
HTTP 200.

This is a **direct-dependency constraint snapshot, not a complete lockfile**:
transitive packages, hashes, package-index state, platform-specific wheels,
and the isolated `hatchling` build backend are not pinned here. `hatchling`
is declared in `pyproject.toml` but was not installed in the runtime virtual
environment, so no runtime version is claimed for it. A future reproducible
release should generate and test a complete platform-specific lock/hashed
artifact set. This V1 record documents the environment that passed the
project checks; it does not establish production deployment reproducibility.

Versions were read locally with Python's `importlib.metadata`, without
importing provider clients, reading `.env`, or making network requests.
`python -m pip check` reported **No broken requirements found**. An attempted
`pip freeze --exclude-editable` also displayed the direct versions but raised
an unrelated Git/Xcode-license warning while looking up local repository
metadata; this table does not rely on that command.
