# syntax=docker/dockerfile:1
FROM node:22-alpine AS build
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/index.html frontend/tsconfig.json frontend/vite.config.ts ./
COPY frontend/src ./src
COPY config/branding.json /config/branding.json
RUN npm run build

FROM nginx:1.28-alpine
COPY deployment/frontend/nginx.conf /etc/nginx/nginx.conf
COPY --from=build /build/dist /usr/share/nginx/html
USER 101:101
EXPOSE 8080
# Skip image entrypoint scripts that try to modify the read-only configuration.
ENTRYPOINT ["nginx"]
CMD ["-g", "daemon off;"]
