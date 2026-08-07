# Stale four-type registry assertion

`.venv/bin/python -m pytest -q` now reports 116 passed and one failure in
`tests/test_api.py::test_the_memory_registry_is_populated_with_the_right_tiers`.

The assertion still expects only:

```python
{"skill": 0, "profile": 1, "fact": 2, "episode": 3}
```

The regenerated canonical seed intentionally includes the two newly required
tier-3 types, so the observed registry also has `{"foresight": 3, "case": 3}`.
Please update the Fable-owned test expectation to include those entries. I did
not edit `tests/`.

The separate ablation suite still passes all 5 tests, including planted-memory
separation.
