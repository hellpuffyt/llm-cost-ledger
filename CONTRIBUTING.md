# Contributing

Thanks for considering a contribution to llm-cost-ledger.

## Development setup

```bash
python -m venv .venv
# Windows
.venv\Scripts\python.exe -m pip install -e ".[dev]"
# macOS/Linux
.venv/bin/python -m pip install -e ".[dev]"
```

## Before opening a pull request

Run the full quality gate locally and make sure it's clean:

```bash
.venv/Scripts/python.exe -m pytest
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m mypy
```

- Add tests for any new behavior, including at least one case that proves
  the feature does *not* fire when it shouldn't (false-positive guards
  matter as much as the happy path, especially in `drift`).
- Keep the tool fully offline: no code path should make a network request
  or expect an API key to be present.
- Only synthetic/fabricated data belongs in `examples/` and `tests/` --
  never a real usage export, account id, or credential.
- Update `CHANGELOG.md` for any user-visible change.
- New models added to the bundled default pricing table should cite the
  provider pricing page the numbers came from in the pull request
  description; the table will still go stale over time and that's fine --
  the README says so.

## Reporting issues

Please include the exact command you ran, the input file shape (a
sanitized excerpt is fine), and the full error message.
