FROM nginx:alpine

COPY index.html /usr/share/nginx/html/index.html
COPY data/zip-county.json /usr/share/nginx/html/data/zip-county.json
COPY data/city-county.json /usr/share/nginx/html/data/city-county.json
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=3s \
  CMD wget -qO- http://127.0.0.1/ || exit 1
