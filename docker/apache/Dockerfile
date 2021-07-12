FROM httpd:alpine

RUN  apk update && apk upgrade && \
     #apk add apache2 && \
     #apk add apache2-proxy && \
     #apk add apache2-ssl && \
     rm -rf /var/cache/apk/*

#COPY ./jason.html /usr/local/apache2/htdocs/
#COPY conf.d/* /etc/apache2/

#CMD  [ "/usr/sbin/httpd", "-D", "FOREGROUND"]
