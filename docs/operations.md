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

## Forgotten password

Run from the repository root (set `COMPOSE_PROJECT_NAME` if your stack uses a custom project name):

```bash
scripts/reset-password.sh
```

It asks for the new password twice without echo, stores a new Argon2 hash and ends all sessions. Nothing is reachable over HTTP; the command runs inside the API container.

## Using FinSight from an iPhone

The stack listens on `127.0.0.1` and the session cookie is `Secure`, so the phone needs an HTTPS address that only you can reach.

Recommended: [Tailscale](https://tailscale.com) on the Mac and the iPhone (private network, no open ports), then on the Mac:

```bash
tailscale serve --bg https / http://127.0.0.1:8080
```

FinSight is then at `https://<mac-name>.<tailnet>.ts.net`. Add that origin to `.env` so the login accepts it, and restart the stack:

```bash
FINSIGHT_ALLOWED_ORIGINS=["https://<mac-name>.<tailnet>.ts.net"]
```

Do not bind to `0.0.0.0` on an untrusted network: bookings would travel unencrypted over Wi-Fi.

On the iPhone: open the address in Safari → Share → **Add to Home Screen** for an app icon. For one-tap imports from the share sheet, create an upload key under **Settings → Import from iPhone** and follow the steps shown there (iOS Shortcut posting to `/api/device/import`). The key can only start imports and can be revoked at any time.
