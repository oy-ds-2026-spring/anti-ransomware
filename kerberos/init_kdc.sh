#!/bin/bash
set -e

# Create KDC database
if [ ! -f /var/lib/krb5kdc/principal ]; then
    kdb5_util create -s -P password
fi

# Create ACL file
mkdir -p /etc/krb5kdc
echo "*/admin@RANSOM.NET *" > /etc/krb5kdc/kadm5.acl

# Start services
/usr/sbin/krb5kdc
/usr/sbin/kadmind

# Add admin principal
kadmin.local -q "addprinc -pw password admin/admin" || true

# Create principals and keytabs for finance nodes
for i in 1 2 3 4; do
    # Client principal for outgoing requests
    kadmin.local -q "addprinc -randkey finance$i" || true
    # Service principal for incoming HTTP requests
    kadmin.local -q "addprinc -randkey HTTP/client-finance$i" || true
    
    rm -f /keytabs/finance$i.keytab
    kadmin.local -q "ktadd -k /keytabs/finance$i.keytab finance$i"
    kadmin.local -q "ktadd -k /keytabs/finance$i.keytab HTTP/client-finance$i"
done

# Create principal and keytab for gateway
kadmin.local -q "addprinc -randkey gateway" || true
rm -f /keytabs/gateway.keytab
kadmin.local -q "ktadd -k /keytabs/gateway.keytab gateway"

# Create principal and keytab for backup-storage
kadmin.local -q "addprinc -randkey backup-storage" || true
rm -f /keytabs/backup-storage.keytab
kadmin.local -q "ktadd -k /keytabs/backup-storage.keytab backup-storage"

chmod 644 /keytabs/*.keytab

# Keep container running
touch /var/log/krb5kdc.log
tail -n 0 -f /var/log/krb5kdc.log # skip init log