# Track P request: update the Stage 1 session-owner API test

`tests/test_api.py::test_a_session_id_reused_by_another_user_starts_clean` now
conflicts with P1's required authorization design: it expects changing
`ChatRequest.user_id` to switch tenants, while P1 requires that field to be
accepted and ignored and tenant identity to come only from the API key.

Please give the `tests/test_api.py` client fixture a default key and rewrite
this test to use two configured tenant keys (or assert that changing only the
body does not change ownership). Track P does not own this existing test file.

---

## Resolution — 2026-09-10 (T3.1)

Done inside Track P, before T3: the `client` fixture in `tests/test_api.py` carries a default
key (`maya-key`) and two configured tenant keys, and
`test_a_session_id_reused_by_another_user_starts_clean` /
`test_a_body_user_id_cannot_reassign_a_session` assert that tenant identity comes from the key,
not the body. Nothing left to action.
