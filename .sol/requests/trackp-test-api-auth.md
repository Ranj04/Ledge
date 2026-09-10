# Track P request: update the Stage 1 session-owner API test

`tests/test_api.py::test_a_session_id_reused_by_another_user_starts_clean` now
conflicts with P1's required authorization design: it expects changing
`ChatRequest.user_id` to switch tenants, while P1 requires that field to be
accepted and ignored and tenant identity to come only from the API key.

Please give the `tests/test_api.py` client fixture a default key and rewrite
this test to use two configured tenant keys (or assert that changing only the
body does not change ownership). Track P does not own this existing test file.
