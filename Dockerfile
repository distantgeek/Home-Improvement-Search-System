FROM nginx:alpine

COPY index.html /usr/share/nginx/html/index.html
COPY data/zip-county.json /usr/share/nginx/html/data/zip-county.json
COPY data/city-county.json /usr/share/nginx/html/data/city-county.json

# nginx template — envsubst substitutes ${MEILI_KEY} at startup from the Docker secret
COPY nginx.conf.template /etc/nginx/templates/default.conf.template

# Secret loader — sourced by the official nginx entrypoint before envsubst runs
COPY docker-entrypoint.d/10-load-meili-secret.sh /docker-entrypoint.d/10-load-meili-secret.sh
RUN chmod +x /docker-entrypoint.d/10-load-meili-secret.sh

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=3s \
  CMD wget -qO- http://localhost/ || exit 1
