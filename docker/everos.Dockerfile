# Self-hosted EverOS.
#
# EverMind publishes no container image, so this is a thin wrapper around the
# documented pip install. Checked against https://github.com/EverMind-AI/EverOS
# on 2026-08-07:
#
#     pip install everos
#     everos init            # writes a .env template
#     everos server start    # FastAPI on 127.0.0.1:8000
#     GET /health -> {"status": "ok"}
#
# Memories are Markdown on disk under ~/.everos, with SQLite and LanceDB
# indexes beside them. That directory is a volume so a container restart does
# not wipe the demo's memory.

FROM python:3.12-slim

# VERIFY-AT-EVENT: LanceDB pulls native wheels; if the install fails on the
# venue machine, `apt-get install -y build-essential` here and rebuild.
RUN pip install --no-cache-dir everos

ENV EVEROS_HOME=/data/everos
WORKDIR /app

# Bind to all interfaces so the compose network can reach it. The container
# keeps EverOS on its own default port 8000; compose maps it to 8077 on the
# host, because OUR service already owns host port 8000.
#
# VERIFY-AT-EVENT: confirm `everos server start` accepts --host/--port. If it
# does not, drop the flags — the default already binds 8000 inside the
# container, and only the host mapping matters.
EXPOSE 8000
CMD ["everos", "server", "start", "--host", "0.0.0.0", "--port", "8000"]
