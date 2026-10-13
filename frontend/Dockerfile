# Frontend: build Vite → estático servido por nginx (target dev para override).
FROM node:22.12-bookworm-slim AS deps
WORKDIR /srv/web
COPY package.json ./
RUN npm install

FROM deps AS dev
COPY . ./
EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]

FROM deps AS build
COPY . ./
RUN npm run build

FROM nginx:1.27-bookworm AS prod
COPY --from=build /srv/web/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD wget -q -O - http://localhost:80/ | grep -q Agenda
