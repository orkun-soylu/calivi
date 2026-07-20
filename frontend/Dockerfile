FROM node:22-alpine AS build

WORKDIR /app
# The lockfile is copied alongside and `npm ci` is used so the build is reproducible.
# (With package.json alone + `npm install`, every build re-resolved the dependencies → a
# transitive update could break code nobody had touched.)
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
