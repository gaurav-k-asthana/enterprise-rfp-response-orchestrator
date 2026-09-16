# VS Code Beginner Guide

Use this guide from top to bottom. Commands are typed into VS Code’s integrated terminal, not into a Python file.

## 1. Open the correct folder

1. Open VS Code.
2. Choose **File → Open Folder…**.
3. Select the folder named `RFP Agentic AI` inside `Documents/AI System Builds`.
4. If VS Code asks whether you trust the authors, choose **Yes, I trust the authors** because this is your local project.
5. The Explorer on the left should show `README.md`, `planning`, `src`, and `tests`.

## 2. Install the Python extension

1. Click the Extensions icon on the left, or press **Shift–Command–X** on macOS.
2. Search for `Python`.
3. Install the extension published by Microsoft.
4. Do not install several unrelated Python extensions yet.

## 3. Open the terminal

1. Choose **Terminal → New Terminal**.
2. A panel opens at the bottom.
3. Confirm the prompt ends with the project folder name.
4. Run `pwd`.

The printed path should end with `AI System Builds/RFP Agentic AI`.

## 4. Create and activate the virtual environment

Run these commands one at a time:

```bash
python3 -m venv .venv
source .venv/bin/activate
python --version
```

The prompt should now begin with `(.venv)`. Python must be 3.10 or newer.

If creation fails, copy the exact error into Codex. Do not install random packages to guess at the fix.

## 5. Tell VS Code to use `.venv`

1. Press **Shift–Command–P**.
2. Type `Python: Select Interpreter`.
3. Select the interpreter whose path contains `.venv/bin/python`.
4. If it is not listed, choose **Enter interpreter path… → Find…**, then select `.venv/bin/python` inside the project.

## 6. Install project dependencies

With `(.venv)` visible in the terminal, run:

```bash
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
```

This can take several minutes. Warnings are not necessarily failures; look at the final lines. If the command ends with an error, send the complete error to Codex.

## 7. Create the private `.env` file

In the terminal, run:

```bash
cp .env.example .env
```

Then click `.env` in the Explorer. Add keys only when a build phase requests them. Never commit or share this file.

Official OpenAI documentation recommends loading API keys from environment variables or a server-side secret manager, not exposing them in browser/client code. This project follows that rule.

## 8. Run the checks

```bash
python -m pytest -q
python -m ruff check .
```

A passing test run ends with a line such as `N passed`. Ruff should end without errors.

## 9. Understand the main folders

- `planning/`: approved design and operating instructions.
- `src/rfp_orchestrator/`: application code Codex builds with you.
- `tests/`: automated checks that protect behavior while code changes.
- `data/`: synthetic documents and RFP cases; never real customer data.
- `.env`: local secrets and configuration; never committed.

## 10. Your normal work loop

1. Ask Codex for the next bounded build step.
2. Review the files Codex changed.
3. Run the tests in the terminal.
4. Launch the app when instructed.
5. Describe what you see or paste the exact error.
6. Commit only after the step works.

You do not need to type application code manually unless you want the practice. Your job is to understand each change, keep credentials private, run checks, and verify behavior.
