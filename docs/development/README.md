# Development

Run the unit suite and static checks from this repository:

```bash
python -m pip install -e '.[dev]'
pytest
ruff check .
mypy
```

Contract tests must use deterministic model and protocol checks without provider credentials.
Provider sandbox acceptance belongs to each adapter and must be labeled separately from local unit
results. Keep public contracts provider-neutral and document any behavior that cannot be safely
normalized.
