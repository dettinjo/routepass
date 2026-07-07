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
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 4321
