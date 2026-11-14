# Publication and security review

This is a review checklist, not an audit attestation. Checkboxes below distinguish
implemented scanner controls from application controls that still need verification.
Never use a real bank export as a test fixture, attach it to an issue, or paste
scanner input into logs. Use identifiers such as `TEST_IBAN_001` instead.

## Publication gate — implemented

- [x] `scripts/privacy_check.py` uses only Python's standard library and local Git;
  it does not call external services or upload content.
- [x] Inspect staged index contents, tracked working-file contents, and every
  locally available commit tree/blob, including other refs, reflogs and dangling
  objects. Inspect commit/tag metadata as well. Git replacement objects are disabled.
- [x] Reject spreadsheet/CSV exports, private runtime directories, database files,
  credentials, logs and non-example environment files by path. `.env.example`
  remains subject to content checks. Forbidden paths are reported without opening
  their contents; their blobs are also excluded from content reads.
- [x] Leave all untracked/ignored files untouched, including the real private root
  XLSX. The gate does not claim those files are safe or suitable for publication.
- [x] Detect private-key markers, common provider token formats, JWT-like strings,
  credential URLs, literal secret assignments and IBAN-like numbers. There is no
  IBAN checksum exemption or hardcoded list of permitted real-looking IBANs.
- [x] Accept explicit synthetic identifiers and empty/template environment values;
  these do not disable independent token, private-key or IBAN rules. Lockfiles
  and licenses have no blanket exemption and are not entropy-scanned.
  Exact nonliteral references `${{ secrets.IDENTIFIER }}` and
  `$(openssl rand -hex POSITIVE_INTEGER)` are also accepted, quoted or unquoted;
  the scanner never evaluates them. GitHub fallback expressions, other expression
  contexts, extra commands/concatenation and literal environment defaults are not
  exempted. An unquoted expression with trailing commentary can be rejected;
  put explanatory comments on a separate line.
  Quoted-key candidates immediately following a ternary `?` (ignoring whitespace)
  are treated as string alternatives, not object assignments. Actual password
  assignments and object keys inside ternary branches remain subject to checks;
  this does not exempt any password vocabulary.
- [x] Optional, explicit screenshot approvals bind a restricted PNG path to exact
  SHA-256 digests. Worktree, index and historical versions are checked separately;
  an approval never follows identical bytes to another filename. Without an
  explicit CLI option, binaries still fail closed.
- [x] Fail closed for missing Git context, shallow/partial repositories, Git read
  errors, oversized content, unsupported binary/text encodings, symlinks,
  submodules and unresolved index entries. Working-file reads do not follow
  symlinks, including parent directories.
- [x] JSON-line output contains paths and rule counts only, never matched contents,
  source lines, credentials, object IDs or raw Git error output. Filenames are
  JSON-escaped to prevent newline/control-character log injection.
- [x] Isolated temporary Git tests cover staged exports, staged secrets with clean
  working copies, deleted historical secrets/exports, dangling blobs, other refs,
  commit messages, placeholders, IBANs, symlinks, exact screenshot approvals,
  manifest validation and fail-closed behavior. No test-directory exemption exists.

Run from the complete local repository **immediately before every push**:

```sh
python3 scripts/privacy_check.py
python3 -m unittest discover -s tests/security -p 'test_privacy_check.py'
```

Exit codes: `0` means no scanner findings, `1` means findings, `2` means inspection
could not complete. Only `0` permits proceeding to the remaining publication
checks. Re-run after any file/index/history change. No hooks or CI enforcement
are implied by this document. A fresh CI checkout often lacks full local history;
it is not a replacement for the local pre-push check.

### Explicitly reviewed synthetic screenshots

Only after manually viewing the **exact image**, verifying that all displayed
data is synthetic, and checking it contains no real names, identifiers, financial
records or credentials, approve its SHA-256 with either:

```sh
python3 scripts/privacy_check.py --reviewed-image "docs/screenshots/dashboard.png=$SHA256"
python3 scripts/privacy_check.py --reviewed-images docs/screenshots/reviewed.json
```

`$SHA256` must be the actual 64-character lowercase hex digest of the reviewed
bytes, not a placeholder. `--reviewed-image` is repeatable. Every distinct
historical version needs its own reviewed digest, even if subsequently deleted;
repeat the path with each separately reviewed digest. Hashes are not printed in
scanner output.

The manifest is **not loaded automatically**. If choosing the manifest option,
create and commit `docs/screenshots/reviewed.json` only after the manual review,
then explicitly pass that option locally and in CI. Its strict schema is:

```json
{
  "synthetic_only": true,
  "manual_review": "Reviewer and date; exact images visually checked as synthetic only",
  "images": [
    {"path": "docs/screenshots/dashboard.png", "sha256": "<64 lowercase hex characters>"}
  ]
}
```

This is a schema example, **not an approval or existing manifest**. Extra fields,
duplicate JSON keys, missing/empty review notes, non-true `synthetic_only`, invalid
paths/hashes and missing/unreadable manifests fail closed. Review notes are a human
assertion, not authenticated proof that review occurred. Changes to the manifest
must receive the same review as changes to screenshot bytes.

Only direct child files matching `docs/screenshots/[A-Za-z0-9][A-Za-z0-9._-]*.png`
qualify. Each approved image is limited to **5 MiB**, must have a PNG signature,
valid chunk lengths/CRCs and a basic IHDR/IDAT/IEND container without trailing
bytes. Optional text, EXIF, unknown and compressed metadata chunks are rejected;
only rendering-related PLTE, tRNS, sRGB, gAMA, cHRM and pHYs are accepted alongside
the required chunks. Strip metadata before reviewing/hashing if needed.

Approval suppresses only the otherwise-applicable binary/encoding rejection.
Secret/IBAN rules still scan ASCII-compatible bytes and chunk payloads. The
scanner does **not** decode pixel streams, perform OCR, inspect rendered pixels
or prove the image is synthetic. Visual review remains mandatory; a hash only
binds that review to exact bytes. Other binaries, unapproved image paths, altered
versions and unreferenced binary blobs without a known approved path still fail.

Counts aggregate working, staged and historical observations, so they are not a
count of unique leaked secrets. A forbidden blob is never read even if also
stored under a different filename; the forbidden-path finding still blocks push.
An orphan blob has no recoverable filename and is reported under a synthetic path.
History deletion alone does not fix a finding: old objects can remain locally.
Do not weaken rules or add a real IBAN to an allowlist to obtain a passing result.
Stop, rotate exposed credentials, and coordinate history/object remediation with
the maintainer. This checker never rewrites history or deletes files.

## Threat model and release checklist — to verify

Assets: raw bank exports, transaction text, account identifiers, balances,
credentials, sessions, backups, AI prompts/responses and notification contents.
Trust boundaries: browser → API; API → database/import filesystem; API → external
AI/observability/notification providers; local development → public Git hosting.
Threats include accidental publication, unauthorized access, malicious uploads,
cross-user reads, prompt injection and unexpected outbound financial disclosure.

- [ ] Review **all** publishable files manually for names, addresses, transaction
  descriptions, account numbers and sensitive information not covered by regexes.
  This heuristic scanner does not detect all PII, secrets, encodings, obfuscation,
  encrypted archives or credentials embedded in otherwise allowed placeholders.
- [ ] Before creating any screenshot approval manifest, visually review each exact
  PNG and every approved historical version as synthetic-only. No screenshot or
  approval manifest is supplied or attested to by this scanner implementation.
- [ ] Ensure this is the intended complete repository, with required remote refs
  fetched by the maintainer. The scanner cannot inspect history absent locally,
  remote caches/forks, separately published artifacts, releases or issue uploads.
- [ ] Confirm the real export remains ignored and outside Docker build contexts,
  frontend assets, deployment bundles, generated reports and test artifacts.
- [ ] Verify authentication bootstrap, password hashing, session expiry, cookie
  security, CSRF protections, authorization and login rate limits with tests.
- [ ] Verify import type/size limits, filename/path traversal defenses, formula
  handling, malformed workbook behavior and transaction rollback using synthetic
  uploads only; confirm no arbitrary filesystem access or executable imports.
- [ ] Check database/network binding, least-privilege deployment, secret generation,
  HTTPS configuration, backup encryption and a tested restore procedure.
- [ ] Verify external AI, tracing and notifications are off by default; explicit
  consent, minimization/redaction, provider destinations, tool access, budgets and
  retry limits must be tested before enabling transmission of financial data.
- [ ] Verify logs/errors/telemetry exclude financial records, tokens, prompts and
  uploaded contents. Review browser storage and exported reports as well.
- [ ] Review dependency lockfiles, vulnerabilities, licenses, CI permissions and
  build integrity. Scanner success is not a dependency or license audit.
- [ ] Independently review this gate and enforce it in the actual push workflow;
  concurrent edits and deliberately bypassing the command remain outside its control.
- [ ] Confirm private vulnerability reporting is available as described in
  `SECURITY.md`; do not disclose sensitive reproductions publicly.
