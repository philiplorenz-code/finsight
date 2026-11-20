# Operations

## Disk space

PostgreSQL runs inside Docker. When the Docker disk fills up (typically from repeated image builds), the database can crash into recovery mode.

- The overview shows a notice when less than 15% of the disk is free (critical below 7%). The numbers come from `GET /api/system/disk`.
- Free space without touching data: `docker builder prune -f` removes the build cache only. Volumes and the database are untouched. Avoid `docker system prune --volumes`.
- Check usage: `docker system df`.

## Scheduled backups

`scripts/scheduled-backup.sh [keep] [directory]` writes a timestamped dump via `scripts/backup.sh`, keeps the newest `keep` files (default 14) and skips when less than 1 GiB is free.

cron (daily at 03:15):

```
15 3 * * * cd /path/to/finsight && scripts/scheduled-backup.sh 14 backups >> backups/backup.log 2>&1
```

macOS launchd: create `~/Library/LaunchAgents/local.finsight.backup.plist` that runs `/bin/bash -lc 'cd /path/to/finsight && scripts/scheduled-backup.sh'` with a `StartCalendarInterval` of 03:15, then `launchctl load` it.

Dumps are plaintext. Keep the directory private (it is git-ignored) and encrypt before copying off-site. Test restores with `scripts/restore.sh <dump> --confirm-replace-database` on a copy first.
