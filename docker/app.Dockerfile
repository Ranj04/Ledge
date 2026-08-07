# MemoryLedger service. Serves the API and the built SPA from one origin.
#
# The SPA is built in a separate stage so the runtime image needs no node.
# Running the app on the host with `python -m app` is equally fine and is what
# EVENT_DAY.md assumes — this exists so `docker compose up` brings up the whole
# thing including EverOS, which is the more robust option on venue wifi.

FROM node:20-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json* ./
RUN npm ci || npm install
COPY web/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY ablation/ ./ablation/
COPY seed/ ./seed/
COPY scripts/ ./scripts/
COPY data/seed/ ./data/seed/
COPY --from=web /web/dist ./web/dist

ENV PORT=8000
EXPOSE 8000
CMD ["python", "-m", "app"]
