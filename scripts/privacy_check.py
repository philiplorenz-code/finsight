#!/usr/bin/env python3
"""Conservative, offline publication gate. No third-party dependencies.

Exit 0: no findings; 1: privacy findings; 2: incomplete/failed inspection.
Only Git-known files/objects are inspected; ignored/untracked exports are never
opened. This is a heuristic gate, not proof that a repository contains no PII.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import zlib


MAX_BYTES = 32 * 1024 * 1024
MAX_IMAGE_BYTES = 5 * 1024 * 1024
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
IMAGE_PATH = re.compile(r"docs/screenshots/[A-Za-z0-9][A-Za-z0-9._-]*\.png\Z")
REVIEW_MANIFEST = "docs/screenshots/reviewed.json"
FORBIDDEN_SUFFIXES = {
    ".xlsx", ".xls", ".xlsm", ".xlsb", ".ods", ".csv", ".tsv",
    ".db", ".sqlite", ".sqlite3", ".dump", ".sql", ".bak",
    ".pem", ".key", ".p12", ".pfx", ".log", ".jsonl", ".parquet",
}
PRIVATE_DIRS = {
    "data", "imports", "exports", "backups", "private", "uploads",
    ".venv", "node_modules", "__pycache__", ".pytest_cache", ".ruff_cache",
    "coverage", "htmlcov", "test-results", "playwright-report",
}
PATTERNS = {
    "private-key": re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----"),
    "provider-token": re.compile(
        r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}"
        r"|sk-(?:proj-|ant-)?[A-Za-z0-9_-]{20,}"
        r"|xox[baprs]-[A-Za-z0-9-]{15,}|(?:AKIA|ASIA)[A-Z0-9]{16})\b"
    ),
    "jwt-token": re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    # Deliberately no checksum requirement and no known-example IBAN exemption.
    "iban-like": re.compile(
        r"(?<![A-Za-z0-9])[A-Z]{2}[0-9]{2}(?:[ -]?[A-Z0-9]{4}){2,7}"
        r"(?:[ -]?[A-Z0-9]{1,3})?(?![A-Za-z0-9])"
    ),
}
CREDENTIAL_URL = re.compile(
    r"\b[a-z][a-z0-9+.-]*://[^\s/:@]+:(\$\{[^{}\r\n]*\}|[^\s/@]+)@", re.I,
)
SECRET_NAME = re.compile(
    r"(?:^|[_-])(?:password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|"
    r"authorization|credential)(?:$|[_-](?:key|token)$)", re.I
)
ASSIGNMENT = re.compile(
    r'''(?<![\w.\-"'])(?<!\$\{)(?:"(?P<json_name>[A-Za-z_][\w.-]*)"|'''
    r"'(?P<single_name>[A-Za-z_][\w.-]*)'|(?P<name>[A-Za-z_][\w.-]*))"
    r'''[ \t]*[:=][ \t]*(?:"(?P<double>[^"\r\n]*)"|'''
    r"'(?P<single>[^'\r\n]*)'|(?P<bare>\$\{\{[^\r\n]*|\$\([^\r\n]*|\$\{[^{}\r\n]*\}|[^\s,#;}\"']+))"
)
SECURE_REFERENCE = re.compile(
    r"(?:\$\{\{[ \t]*secrets\.[A-Za-z_][A-Za-z0-9_]*[ \t]*\}\}|"
    r"\$\([ \t]*openssl[ \t]+rand[ \t]+-hex[ \t]+[1-9][0-9]*[ \t]*\))\Z"
)
PLACEHOLDER = re.compile(
    r"(?:TEST(?:[_-][A-Za-z0-9_-]+)?|EXAMPLE(?:[_-][A-Za-z0-9_-]+)?|"
    r"SYNTHETIC(?:[_-][A-Za-z0-9_-]+)?|replace[-_]me(?:[-_].*)?|"
    r"your[-_].*|change[-_]me|<[^<>\r\n]+>|\$[A-Z_][A-Z0-9_]*)\Z",
    re.I,
)


class InspectionError(Exception):
    """Intentionally carries no subprocess output or private file contents."""


def is_placeholder(value: str) -> bool:
    if not value or PLACEHOLDER.fullmatch(value) or SECURE_REFERENCE.fullmatch(value):
        return True
    # A required-variable error message is not a credential; a nonempty default
    # value CAN be one, so it must itself be explicitly synthetic.
    if value.startswith("${") and value.endswith("}"):
        substitution = re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(?:([:]?[-+?])(.*))?", value[2:-1])
        if substitution:
            operation, default = substitution.groups()
            return operation is None or operation.endswith("?") or is_placeholder(default)
    return False


def git(root: Path, *args: str) -> bytes:
    env = dict(os.environ, GIT_NO_REPLACE_OBJECTS="1", GIT_NO_LAZY_FETCH="1", LC_ALL="C")
    try:
        result = subprocess.run(
            ["git", "--no-pager", "-C", str(root), *args],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env, check=False,
        )
    except OSError:
        raise InspectionError from None
    if result.returncode:
        raise InspectionError
    return result.stdout


def path_rule(path: str) -> str | None:
    p = PurePosixPath(path)
    if p.is_absolute() or ".." in p.parts:
        return "unsafe-path"
    parts = tuple(part.lower() for part in p.parts)
    name = parts[-1] if parts else ""
    if name != ".env.example" and (name.endswith(".env") or ".env." in name):
        return "private-env"
    if any(part in PRIVATE_DIRS for part in parts[:-1]):
        return "private-runtime-path"
    if (PurePosixPath(name).suffix in FORBIDDEN_SUFFIXES
            or re.search(r"\.(?:sqlite\w*|db)-(?:wal|shm|journal)$", name)
            or name in {".ds_store", ".coverage", ".git-credentials", ".netrc",
                        "id_rsa", "id_ed25519", "credentials.json", "secrets.json"}
            or name.endswith((".pyc", ".pyo"))):
        return "private-file"
    return None


def text_rules(text: str) -> Counter[str]:
    findings = Counter({name: len(pattern.findall(text)) for name, pattern in PATTERNS.items()})
    findings["credential-url"] = sum(
        not is_placeholder(match[1]) for match in CREDENTIAL_URL.finditer(text)
    )
    for match in ASSIGNMENT.finditer(text):
        name = match["json_name"] or match["single_name"] or match["name"]
        if not SECRET_NAME.search(name):
            continue
        if match["json_name"] is not None or match["single_name"] is not None:
            preceding = match.start() - 1
            while preceding >= 0 and text[preceding].isspace():
                preceding -= 1
            # In `condition ? 'new-password' : 'current-password'`, the
            # first string is a ternary alternative, not a quoted object key.
            # An object inside that alternative still has `{` before its key.
            if preceding >= 0 and text[preceding] == "?":
                continue
        quoted = match["double"] is not None or match["single"] is not None
        value = next(match[key] for key in ("double", "single", "bare") if match[key] is not None)
        if not quoted:
            value = value.rstrip(" \t")
        # A safe reference followed by concatenation or an additional scalar is
        # not the exact reference. Do not accept just its safe-looking prefix.
        reference_suffix = False
        if SECURE_REFERENCE.fullmatch(value) and quoted:
            line_end = text.find("\n", match.end())
            tail = text[match.end():line_end if line_end >= 0 else len(text)].lstrip(" \t\r")
            reference_suffix = bool(tail and tail[0] not in ",;)}]#")
        if is_placeholder(value) and not reference_suffix:
            continue
        # Unquoted source expressions (settings.secret, None, Field(...), etc.)
        # aren't literal credentials. Uppercase env assignments are literals.
        if quoted or (name.isupper() and (value.startswith(("${", "$(")) or not re.search(r"[()\[\]{}]", value))
                      and value not in {"None", "null", "false", "true"}):
            findings["secret-assignment"] += 1
    return +findings


def content_rules(data: bytes) -> Counter[str]:
    if b"\0" in data:
        return Counter({"binary-content": 1})
    try:
        return text_rules(data.decode("utf-8-sig"))
    except UnicodeError:
        return Counter({"unsupported-encoding": 1})


def add_image_review(reviews: dict[str, set[str]], path: str, digest: str) -> None:
    if not isinstance(path, str) or not IMAGE_PATH.fullmatch(path):
        raise InspectionError
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise InspectionError
    reviews.setdefault(path, set()).add(digest)


def load_image_reviews(root: Path, specifications: list[str], manifest: str | None) -> dict[str, set[str]]:
    reviews: dict[str, set[str]] = {}
    for specification in specifications:
        path, separator, digest = specification.partition("=")
        if not separator:
            raise InspectionError
        add_image_review(reviews, path, digest)
    if manifest is not None:
        if manifest != REVIEW_MANIFEST:
            raise InspectionError
        raw = worktree_bytes(root, manifest)
        if raw is None or len(raw) > 65536:
            raise InspectionError

        def unique_keys(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise InspectionError
                result[key] = value
            return result

        document = json.loads(raw, object_pairs_hook=unique_keys)
        if (not isinstance(document, dict)
                or set(document) != {"synthetic_only", "manual_review", "images"}
                or document["synthetic_only"] is not True
                or not isinstance(document["manual_review"], str)
                or not document["manual_review"].strip()
                or not isinstance(document["images"], list)
                or not document["images"]):
            raise InspectionError
        if content_rules(raw):
            raise InspectionError
        for image in document["images"]:
            if not isinstance(image, dict) or set(image) != {"path", "sha256"}:
                raise InspectionError
            add_image_review(reviews, image["path"], image["sha256"])
    return reviews


def image_rules(data: bytes, digests: set[str]) -> Counter[str]:
    """Exact review binding, basic container validation, and ASCII secret scans.

    No OCR or image decompression: the human review is a separate trust boundary.
    Reject optional metadata rather than allowing compressed/unreviewed text.
    """
    if len(data) > MAX_IMAGE_BYTES:
        return Counter({"reviewed-image-size": 1})
    findings = text_rules(data.decode("latin-1"))
    if hashlib.sha256(data).hexdigest() not in digests:
        findings["reviewed-image-hash"] += 1
    if not data.startswith(PNG_SIGNATURE):
        findings["reviewed-image-format"] += 1
        return findings
    position = len(PNG_SIGNATURE)
    chunks = []
    while position + 12 <= len(data):
        size = int.from_bytes(data[position:position + 4], "big")
        end = position + 12 + size
        if end > len(data):
            break
        kind = data[position + 4:position + 8]
        payload = data[position + 8:end - 4]
        crc = int.from_bytes(data[end - 4:end], "big")
        if zlib.crc32(kind + payload) != crc:
            break
        # Chunk framing must not hide a token's word boundary.
        findings.update(text_rules(payload.decode("latin-1")))
        if kind not in {b"IHDR", b"PLTE", b"IDAT", b"IEND", b"tRNS", b"sRGB", b"gAMA", b"cHRM", b"pHYs"}:
            findings["reviewed-image-metadata"] += 1
        chunks.append(kind)
        if kind == b"IHDR" and (size != 13 or not int.from_bytes(payload[:4], "big")
                               or not int.from_bytes(payload[4:8], "big")):
            findings["reviewed-image-format"] += 1
        position = end
        if kind == b"IEND":
            if size:
                findings["reviewed-image-format"] += 1
            break
    if (position != len(data) or not chunks or chunks[0] != b"IHDR"
            or chunks[-1] != b"IEND" or chunks.count(b"IHDR") != 1 or b"IDAT" not in chunks):
        findings["reviewed-image-format"] += 1
    return findings


def worktree_bytes(root: Path, path: str) -> bytes | None:
    """Do not follow file OR directory symlinks, including during open races."""
    descriptors: list[int] = []
    try:
        descriptors.append(os.open(root, os.O_RDONLY | os.O_DIRECTORY))
        parts = PurePosixPath(path).parts
        for part in parts[:-1]:
            descriptors.append(os.open(
                part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptors[-1],
            ))
        descriptors.append(os.open(
            parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptors[-1],
        ))
        info = os.fstat(descriptors[-1])
        if not stat.S_ISREG(info.st_mode):
            raise InspectionError
        if info.st_size > MAX_BYTES:
            return None
        chunks = []
        total = 0
        while chunk := os.read(descriptors[-1], min(65536, MAX_BYTES + 1 - total)):
            chunks.append(chunk)
            total += len(chunk)
            if total > MAX_BYTES:
                return None
        return b"".join(chunks)
    except FileNotFoundError:
        return b""  # Deleted working file: its index/history still gets inspected.
    except OSError:
        raise InspectionError from None
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def inspect(root: Path, reviewed_images: list[str] | None = None,
            reviewed_manifest: str | None = None) -> dict[str, Counter[str]]:
    root = Path(os.fsdecode(git(root, "rev-parse", "--show-toplevel")).strip()).resolve()
    if git(root, "rev-parse", "--is-shallow-repository").strip() != b"false":
        raise InspectionError
    config = git(root, "config", "--list").lower()
    if b"extensions.partialclone=" in config or re.search(rb"remote\.[^\n]+\.promisor=true", config):
        raise InspectionError
    reviews = load_image_reviews(root, reviewed_images or [], reviewed_manifest)

    findings: dict[str, Counter[str]] = defaultdict(Counter)
    paths: dict[str, set[str]] = defaultdict(set)
    forbidden_blobs: set[str] = set()
    working: set[str] = set()

    def entry(mode: str, oid: str, path: str) -> None:
        paths[oid].add(path)
        rule = path_rule(path)
        if rule:
            findings[path][rule] = 1
            forbidden_blobs.add(oid)  # Never open a forbidden export, even via another name.
        if mode not in {"100644", "100755"}:
            findings[path]["symlink-or-submodule"] = 1
            forbidden_blobs.add(oid)

    # Index includes staged-only files and conflict stages, not just HEAD.
    for record in git(root, "ls-files", "--stage", "-z").split(b"\0"):
        if not record:
            continue
        metadata, raw_path = record.split(b"\t", 1)
        mode, oid, stage = metadata.decode("ascii").split()
        path = os.fsdecode(raw_path)
        entry(mode, oid, path)
        working.add(path)
        if stage != "0":
            findings[path]["unmerged-index"] = 1
        if not oid.strip("0"):
            findings[path]["incomplete-index"] = 1

    # Enumerating ALL local objects includes all refs, reflogs and dangling
    # commits/blobs. No revision-range or HEAD-only loophole; replacements off.
    objects = []
    for line in git(root, "cat-file", "--batch-all-objects", "--batch-check=%(objectname) %(objecttype) %(objectsize)").splitlines():
        oid, kind, size = line.decode("ascii").split()
        objects.append((oid, kind, int(size)))
    seen_trees: set[str] = set()
    for oid, kind, _size in objects:
        if kind != "commit":
            continue
        tree = git(root, "rev-parse", oid + "^{tree}").decode("ascii").strip()
        if tree in seen_trees:
            continue
        seen_trees.add(tree)
        for record in git(root, "ls-tree", "-r", "-z", tree).split(b"\0"):
            if not record:
                continue
            metadata, raw_path = record.split(b"\t", 1)
            mode, _kind, blob = metadata.decode("ascii").split()
            entry(mode, blob, os.fsdecode(raw_path))

    for path in sorted(working):
        if path_rule(path):
            continue
        try:
            data = worktree_bytes(root, path)
        except InspectionError:
            findings[path]["unreadable-working-file"] = 1
            continue
        findings[path].update({"oversized-content": 1} if data is None else
                              image_rules(data, reviews[path]) if path in reviews else content_rules(data))

    for oid, kind, size in objects:
        if kind not in {"blob", "commit", "tag"} or oid in forbidden_blobs:
            continue
        labels = paths.get(oid) or {f"<unreferenced-{kind}>" if kind == "blob" else f"<{kind}-metadata>"}
        data = None if size > MAX_BYTES else git(root, "cat-file", kind, oid)
        for path in labels:
            rules = (Counter({"oversized-content": 1}) if data is None else
                     image_rules(data, reviews[path]) if kind == "blob" and path in reviews else content_rules(data))
            findings[path].update(rules)
    return {path: rules for path, rules in findings.items() if rules}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="Git working tree (default: current directory)")
    parser.add_argument("--reviewed-image", action="append", default=[], metavar="PATH=SHA256",
                        help="explicitly approve an exact manually reviewed synthetic PNG (repeatable)")
    parser.add_argument("--reviewed-images", metavar="MANIFEST",
                        help="explicit opt-in to docs/screenshots/reviewed.json")
    args = parser.parse_args(argv)
    try:
        findings = inspect(args.repo, args.reviewed_image, args.reviewed_images)
    except (InspectionError, OSError, ValueError):
        print(json.dumps({"rules": {"inspection-incomplete": 1}}))
        return 2
    totals: Counter[str] = Counter()
    for path, rules in sorted(findings.items()):
        totals.update(rules)
        print(json.dumps({"path": path, "rules": dict(sorted(rules.items()))}, ensure_ascii=True))
    print(json.dumps({"rules": dict(sorted(totals.items()))}))
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
