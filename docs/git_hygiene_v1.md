# V1 Git and credential hygiene review

**Step 5.16 review, September 16, 2026.** This is a local, path-and-policy
audit. No credential value, `.env` content, raw output, or trace payload was
printed or copied into this report.

## Rules reviewed

The repository's [`.gitignore`](../.gitignore) excludes the live `.env`,
environment backups such as `.env.local`, `.envrc`, Streamlit's
`.streamlit/secrets.toml`, `.venv/`, Python and test/lint/type caches,
`outputs/` (including evaluation raw runs and LangSmith trace receipts),
local `.vscode/` settings, common private-key file extensions, and
credential/secret JSON filenames. The shareable `.env.example` and
`.streamlit/config.toml` remain eligible for source control.

An independent Git-wildmatch policy check exercised 17 representative
paths with **zero mismatches**. It explicitly confirmed that `.env` and
files under `outputs/` are ignored while `.env.example` and the frozen
synthetic evaluation cases are not. A path-name inventory found only `.env`
and `.env.example` among root environment files, and no separate key or
credential-named file outside the ignored virtual environment and outputs.
An allowlisted scan of nonignored working-tree files found no known
OpenAI/Pinecone/LangSmith key-prefix or private-key-header pattern. This is
not a proof against every possible credential format.

## Git state at Step 5.16 and follow-up

At Step 5.16, the local `.git/HEAD` pointed to `main`, but there was no
`refs/heads/main`, packed-refs file, or Git index. Therefore there was **no
project branch commit or staging index** to contain `.env`, caches, outputs,
or trace files. Two internal Codex snapshot refs were inspected through
their referenced object trees without printing blob contents: 26 unique
file paths, zero private paths, and zero known key-pattern blob matches.

At that step, the installed Homebrew Git binary was x86_64 and could not run
on this arm64 machine; Apple's Git was blocked by an unaccepted Xcode
license. Consequently, `git status`, `git ls-files`, and `git check-ignore`
could not be used. No Git configuration, history, or license state was
changed during Step 5.16.

**September 16 follow-up:** The user reviewed/accepted the Apple Xcode
license and reported Apple Git 2.54.0. The real Git status showed no commits
on `main` and no remote. We staged the 296 eligible paths solely for an
index review. `git check-ignore` confirmed that `.env`, `.venv/`, `outputs/`,
and `.streamlit/secrets.toml` are excluded. The staged path list contains no
live environment file, local output, virtual environment, or Streamlit
secrets file. A staged text scan found no known provider-key prefix, GitHub
token prefix, or private-key header. The sole working-tree heuristic hit was
an intentionally fake test error string; a byte scan of the static PDF text
streams found none of the listed prefixes. This is a bounded pattern scan,
not a guarantee against all possible sensitive data.

The user reviewed and approved the staged paths, including the journal and
draft report. On September 22, VS Code authenticated with GitHub and published
`main` to the existing public repository. A remote read verified that
`refs/heads/main` exactly matched local commit `f89196e`. No release tag has
been created; the separate Step 5.19 release freeze remains pending.

No ignored credential, virtual-environment, raw-output, or Streamlit-secret
path was published. Keep `.env` closed during screen recording even though it
is ignored by Git; recording and source-control safety are separate boundaries.
