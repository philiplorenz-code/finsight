# Paperless-ngx next to FinSight

Paperless-ngx is the document archive (invoices, contracts, receipts, letters). It runs as its own compose
project on this Mac, only on `127.0.0.1:8010`, with its own database and volumes. FinSight talks to it with an
API token:

- **Receipts → Paperless:** "In Paperless ablegen" on a receipt sends the image with title
  "Kassenzettel <merchant> <date>" and the receipt date. Each receipt is sent once.
- **Booking → documents:** the booking detail lists Paperless documents that match the merchant, with a link.
- **Settings → Paperless:** shows whether the connection works.

FinSight sends only the receipt image, a title and a date. No bookings, no amounts, no account data.

## 1. Start Paperless

The secrets live in `~/Paperless/.env` (mode 600, never committed; template: `infrastructure/paperless/env.example`).
Documents dropped into `~/Paperless/consume` are imported automatically.

```bash
docker compose -p finsight-paperless --env-file ~/Paperless/.env -f infrastructure/paperless/docker-compose.yml up -d
```

Open http://127.0.0.1:8010. The first start takes a minute (database migrations, OCR languages).

## 2. Create your admin account (you, not the agent)

```bash
docker compose -p finsight-paperless --env-file ~/Paperless/.env -f infrastructure/paperless/docker-compose.yml exec webserver createsuperuser
```

Pick user name and password yourself; FinSight never needs them.

## 3. Create an API token and connect FinSight

In Paperless: user menu → **My Profile** → API token → create (circular arrow). Add to FinSight's `.env`
(the one next to `docker-compose.yml` of the real stack) and paste the token between the quotes of `PAPERLESS_TOKEN`:

```
PAPERLESS_URL=http://host.docker.internal:8010
PAPERLESS_TOKEN=""
PAPERLESS_PUBLIC_URL=http://127.0.0.1:8010
```

`host.docker.internal` is how FinSight's API container reaches a port on the Mac. Then recreate the API:

```bash
COMPOSE_PROJECT_NAME=finsight-handoff docker compose up -d api worker
```

Settings → Paperless should now say "Verbunden". To disconnect, remove the lines and recreate again; to revoke
access, delete the token in Paperless.

## Backup

Paperless has its own exporter, which writes all documents and metadata to `~/Paperless/export`:

```bash
docker compose -p finsight-paperless --env-file ~/Paperless/.env -f infrastructure/paperless/docker-compose.yml exec webserver document_exporter ../export
```

Never run `down -v` on this project, it deletes the archive volumes.

## Later: Lexware Office

See `lexware-office.md`. The intended split is that Paperless keeps everything and only business receipts
go on to Lexware.
