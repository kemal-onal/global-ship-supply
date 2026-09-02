# Build stage
FROM node:20-alpine AS builder

WORKDIR /app

# Copy lockfile + manifest first for layer caching
COPY package.json package-lock.json* ./
RUN npm install --no-audit --no-fund

# Copy source and build
COPY . .
ARG VITE_API_BASE=/api
ENV VITE_API_BASE=${VITE_API_BASE}
RUN npm run build

# Runtime stage
FROM nginx:1.25-alpine

# Inject the API base into the SPA at runtime via envsubst on a template
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
    CMD wget --quiet --tries=1 --spider http://localhost/ || exit 1

EXPOSE 80
