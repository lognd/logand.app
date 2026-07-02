# Nightly pg_dump + storage-volume tarball, pushed off-box via rclone to
# R2. See docs/design/11-deployment.md and docs/secrets.md's BACKUP_R2_*
# section for the credentials this needs.
FROM postgres:16-alpine

RUN apk add --no-cache tar gzip dcron rclone

COPY backup.sh /usr/local/bin/backup.sh
RUN chmod +x /usr/local/bin/backup.sh

# Nightly at 03:00.
RUN echo "0 3 * * * /usr/local/bin/backup.sh >> /var/log/backup.log 2>&1" > /etc/crontabs/root

CMD ["crond", "-f", "-l", "2"]
