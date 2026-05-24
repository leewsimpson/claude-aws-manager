# Frontend image — Vite dev server (PoC runs the dev server for live reload
# and the /api proxy). Build context is ../frontend (set in docker-compose.yml).
FROM node:22-slim

WORKDIR /app

# Install dependencies first (cached layer) using only the manifests.
COPY package.json package-lock.json* ./
RUN npm install

COPY . .

EXPOSE 5173

# host flag binds to 0.0.0.0 so the dev server is reachable from the host.
CMD ["npm", "run", "dev", "--", "--host"]
