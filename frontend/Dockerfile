FROM node:24-bookworm-slim AS builder
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm install --global npm@12.2.2 && npm ci
COPY frontend ./
COPY .prettierrc.json /app/.prettierrc.json
RUN npm run build

FROM nginx:1.28-alpine AS runtime
COPY infrastructure/docker/nginx.conf /etc/nginx/nginx.conf
COPY --from=builder /app/frontend/dist /usr/share/nginx/html
USER 101:101
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s CMD wget -q -O /dev/null http://127.0.0.1:8080/healthz || exit 1
ENTRYPOINT ["nginx", "-g", "daemon off;"]
