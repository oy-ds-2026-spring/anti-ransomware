FROM ubuntu:20.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y krb5-kdc krb5-admin-server && rm -rf /var/lib/apt/lists/*
RUN mkdir /keytabs
COPY krb5.conf /etc/krb5.conf
COPY init_kdc.sh /init_kdc.sh
RUN chmod +x /init_kdc.sh
CMD ["/init_kdc.sh"]