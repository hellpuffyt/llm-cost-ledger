"""llm-cost-ledger: attribute LLM API spend per project, model and prompt.

Ingests provider usage exports (OpenAI-style and Anthropic-style CSV/JSON),
normalises them into a single internal record shape, prices them against a
user-configurable pricing table, attributes spend to projects/features via
tag mapping rules, and can detect statistically meaningful drift in
cost-per-request between two periods.
"""

__version__ = "0.1.0"
