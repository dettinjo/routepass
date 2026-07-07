# Astro/Starlight static docs site. Builds to static HTML and serves via nginx.
# Listens on 4321 to match INTERNAL_DOCS_URL's convention (frontend/next.config.ts).
FROM node:20-alpine AS builder
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
RUN sed -i 's/listen\s*80;/listen 4321;/' /etc/nginx/conf.d/default.conf && \
    # Reverse-proxied behind Next.js (rewrites /docs/* here without preserving the
    # public Host header): absolute_redirect off makes nginx's directory-trailing-
    # slash redirects relative, so it doesn't leak the internal "docs:4321" hostname
    # into the Location header returned to the browser.
    sed -i '/listen 4321;/a\    absolute_redirect off;' /etc/nginx/conf.d/default.conf
EXPOSE 4321
