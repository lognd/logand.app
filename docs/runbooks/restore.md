# Runbook: restoring from backup

Referenced from [design/11-deployment.md](../design/11-deployment.md)'s
backup section, written once the backend/backup mechanism actually
existed to describe. See [deployment.md](../deployment.md)'s "Known
limitation: backups aren't off-box yet" note first -- as of writing,
`ops/backup.sh` stages backups locally on the VPS only, so "restore"
today means restoring from that local staging directory, not yet from
true off-box storage.

## What gets backed up

- A full `pg_dump` of the Postgres database (`postgres.sql.gz`).
- A tarball of the budget-evidence volume (`evidence.tar.gz`) -- the
  uploaded receipts/evidence files from [design/05-budget.md](../design/05-budget.md).

Both staged nightly under `/backup/<timestamp>/` inside the `backup`
container's volume (see `docker-compose.yml`'s `backup_staging` volume
and `ops/backup.sh`).

## Restoring the database

1. **Stop the backend first** -- don't restore into a database another
   process is actively writing to.
   ```bash
   docker compose stop backend
   ```
2. Pick the backup to restore from (list what's staged):
   ```bash
   docker compose exec backup ls /backup
   ```
3. Drop and recreate the schema, then restore:
   ```bash
   docker compose exec postgres psql -U logand -d logand -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
   docker compose exec backup sh -c "gunzip -c /backup/<timestamp>/postgres.sql.gz" | \
     docker compose exec -T postgres psql -U logand -d logand
   ```
4. Bring the backend back up and confirm the data looks right:
   ```bash
   docker compose up -d backend
   curl -s https://yourdomain/api/me   # expect 401 (backend is answering), then spot-check real data via the admin UI
   ```

## Restoring budget evidence files

```bash
docker compose exec backup sh -c "tar -xzf /backup/<timestamp>/evidence.tar.gz -C /tmp/restored"
```
Then copy `/tmp/restored`'s contents back into the real
`budget_evidence` volume (mount it alongside and `cp -a`, or use
`docker cp` between containers) -- there's no single command for this
yet since the two volumes aren't mounted into the same container by
default; do this as a one-off manual step.

## After any restore

- Re-check `alembic_version` matches what `alembic upgrade head` (run
  via `docker compose --profile migrate run --rm migrate`) expects --
  a backup taken before a migration was applied needs that migration
  re-run after restoring.
- Spot-check a few real records through the actual UI (an invoice, a
  budget entry) rather than trusting row counts alone.
- If this was a real incident (not a drill), write down what happened
  and when in whatever the operator's own incident log is -- this
  runbook doesn't prescribe one, but "we restored from backup" is worth
  recording somewhere durable.
