FROM node:26-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.31-alpine
# Rendered by the image's entrypoint into /etc/nginx/conf.d/default.conf; only the two FINSIGHT_ variables
# are substituted, nginx's own $variables stay untouched.
ENV FINSIGHT_API_UPSTREAM=api:8000 FINSIGHT_NGINX_RESOLVER=127.0.0.11 NGINX_ENVSUBST_FILTER=^FINSIGHT_
COPY nginx.conf /etc/nginx/templates/default.conf.template
COPY --from=build --chown=101:101 /app/dist /usr/share/nginx/html
USER 101:101
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s CMD wget -q -O /dev/null http://127.0.0.1:8080/healthz || exit 1
