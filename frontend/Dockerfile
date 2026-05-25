# Git Trainer frontend — multi-stage: збірка Vite → роздача через nginx.
# node:24 збігається з хост-середовищем (lock-файл згенеровано ним).
FROM node:24-alpine AS build
WORKDIR /app

COPY package*.json ./
# npm install (не ci): стійкий до крос-платформних optional-залежностей
# (rolldown/oxc/lightningcss native bindings), яких лок може не містити.
RUN npm install --no-audit --no-fund

COPY . .
# VITE_* вшиваються у бандл на етапі build (статика), тож приходять як build-args.
ARG VITE_API_URL
ARG VITE_WS_URL
ENV VITE_API_URL=$VITE_API_URL \
    VITE_WS_URL=$VITE_WS_URL
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
