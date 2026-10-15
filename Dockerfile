# Stage 1: install dependencies
FROM node:25-alpine AS deps
RUN npm install -g pnpm@10.33.0
WORKDIR /app
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile

# Stage 2: build Next.js
FROM node:25-alpine AS builder
RUN npm install -g pnpm@10.33.0
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN pnpm build

# Stage 3: runtime with Racket
FROM node:25-bookworm-slim AS runner
WORKDIR /app

RUN groupadd --system app && useradd --system --gid app --create-home app \
    && apt-get update && apt-get install -y --no-install-recommends \
    racket \
    && rm -rf /var/lib/apt/lists/*

ENV NODE_ENV=production
ENV RACKET_BIN=/usr/bin/racket
ENV PORT=3000
ENV HOSTNAME=0.0.0.0

COPY --chown=app:app --from=builder /app/.next/standalone ./
COPY --chown=app:app --from=builder /app/.next/static ./.next/static
COPY --chown=app:app --from=builder /app/examples ./examples
COPY --chown=app:app --from=builder /app/app/api/run/_runner.rkt \
                    /app/app/api/run/_json-value.rkt \
                    /app/app/api/run/_tracking.rkt \
                    /app/app/api/run/_tracking-assign.rkt \
                    /app/app/api/run/_tracking-init-env.rkt \
                    /app/app/api/run/_stream-parser.rkt \
                    ./app/api/run/

USER app
EXPOSE 3000
CMD ["node", "server.js"]
