# Nightly pg_dump + budget-evidence tarball, pushed off-box. See docs/design/11-deployment.md.
# NOTE(logan): this is a stub -- backup.sh needs a real off-box destination (object storage
# bucket or second VPS) wired in before this is trustworthy. Do not rely on it yet.
FROM postgres:16-alpine

RUN apk add --no-cache tar gzip dcron

COPY backup.sh /usr/local/bin/backup.sh
RUN chmod +x /usr/local/bin/backup.sh

# Nightly at 03:00.
RUN echo "0 3 * * * /usr/local/bin/backup.sh >> /var/log/backup.log 2>&1" > /etc/crontabs/root

CMD ["crond", "-f", "-l", "2"]
