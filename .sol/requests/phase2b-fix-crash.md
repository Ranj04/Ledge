## Browser verification environment limitation

`npm run build` succeeds and the real FastAPI app was exercised in-process through
HTTPX's ASGI transport, including streamed SSE payloads for tiered and naive turns.
Direct browser verification was unavailable in this Codex run: the browser runtime
reported no available browsers, `curl localhost:8000` found no running server, and
starting the existing app on either `0.0.0.0:8000` or `127.0.0.1:8000` was blocked by
the managed sandbox with `operation not permitted`.

No app change is requested. Please perform the final visible browser click-through
from the host-owned server if that confirmation is still required.
