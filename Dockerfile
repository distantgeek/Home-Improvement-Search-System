FROM httpd:alpine

COPY index.html /usr/local/apache2/htdocs/index.html
COPY data/zip-county.json /usr/local/apache2/htdocs/data/zip-county.json

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=3s \
  CMD wget -qO- http://localhost/ || exit 1
