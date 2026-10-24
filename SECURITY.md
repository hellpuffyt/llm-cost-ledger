# Security policy

## Supported versions

Only the latest commit on `main` receives fixes. There are no maintained release branches.

## Reporting a vulnerability

Please report vulnerabilities privately through GitHub's advisory form:
https://github.com/hellpuffyt/llm-cost-ledger/security/advisories/new

Do not open a public issue for a suspected vulnerability. Include the version or commit,
a minimal reproduction, and the impact you observed. You should receive an acknowledgement
within a few days; fixes are released as soon as they are verified.

## Scope

llm-cost-ledger is offline: it reads local usage-export, pricing and mapping files and never makes network requests or reads API keys. YAML is loaded with `yaml.safe_load`. Relevant reports include: any code path that performs network I/O, executes content from an input file, writes outside the requested `--output` path, or produces a wrong dollar figure from valid input.
