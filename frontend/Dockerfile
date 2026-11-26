# Stage 1: Build
FROM node:18-alpine AS builder

# 主前端保持 /assets/；独立素材前端改为 /asset-static/，避免与页面 /assets 抢路径。
ARG VITE_PUBLIC_BASE=/
ENV VITE_PUBLIC_BASE=${VITE_PUBLIC_BASE}

WORKDIR /app

# Copy package files and install dependencies
COPY package.json package-lock.json ./
RUN npm install --no-audit --no-fund  --registry=https://registry.npmmirror.com

# Copy source code
COPY . .

# Build the application. Force the source config: tsc may emit a stale vite.config.js
# into the build context, and Vite otherwise prefers that generated file over .ts.
RUN npm run build -- --config vite.config.ts

# Stage 2: Serve with nginx
FROM nginx:alpine
ARG NGINX_CONFIG=nginx.conf

# Copy built assets from builder stage
COPY --from=builder /app/dist /usr/share/nginx/html

# Copy nginx configuration
RUN rm /etc/nginx/conf.d/default.conf
COPY ${NGINX_CONFIG} /etc/nginx/conf.d/

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]