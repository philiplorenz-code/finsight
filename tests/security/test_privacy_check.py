"""Only synthetic content in disposable Git repositories; no real export reads."""

from contextlib import redirect_stdout
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zlib


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "privacy_check.py"
SPEC = importlib.util.spec_from_file_location("privacy_check", SCRIPT)
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)


class PrivacyCheckTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="finsight-privacy-test-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.git("init", "-q")
        self.git("config", "user.name", "TEST")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "commit.gpgsign", "false")

    def git(self, *args):
        return subprocess.run(
            ["git", "-C", str(self.root), *args], check=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=dict(os.environ, GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull),
        ).stdout

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def scan(self, *options):
        output = io.StringIO()
        with redirect_stdout(output):
            status = checker.main(["--repo", str(self.root), *options])
        lines = [json.loads(line) for line in output.getvalue().splitlines()]
        return status, output.getvalue(), lines

    @staticmethod
    def png(pixel=b"\0\0\0", metadata=None):
        def chunk(kind, payload):
            return (len(payload).to_bytes(4, "big") + kind + payload
                    + zlib.crc32(kind + payload).to_bytes(4, "big"))

        header = chunk(b"IHDR", (1).to_bytes(4, "big") * 2 + b"\x08\x02\0\0\0")
        extra = chunk(b"tEXt", metadata) if metadata is not None else b""
        return (checker.PNG_SIGNATURE + header + extra
                + chunk(b"IDAT", zlib.compress(b"\0" + pixel)) + chunk(b"IEND", b""))

    def stage_png(self, data, path="docs/screenshots/dashboard.png"):
        destination = self.root / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        self.git("add", path)
        return path + "=" + hashlib.sha256(data).hexdigest()

    def manifest(self, review):
        path, digest = review.split("=", 1)
        document = {"synthetic_only": True, "manual_review": "TEST manual visual review note",
                    "images": [{"path": path, "sha256": digest}]}
        self.write(checker.REVIEW_MANIFEST, json.dumps(document))
        self.git("add", checker.REVIEW_MANIFEST)
        return document

    def test_clean_placeholders_lockfiles_license_and_synthetic_identifiers(self):
        self.write(".env.example", "SECRET_KEY=\nAI_API_KEY=${AI_API_KEY:-}\nSETUP_TOKEN=<generate-locally>\n")
        self.write("package-lock.json", '{"integrity":"sha512-abcdefghijklmnopqrstuvwxyz0123456789+/=="}')
        self.write("LICENSE", "MIT License\nCopyright (c) TEST\nPermission is hereby granted, free of charge.\n")
        self.write("fixtures.json", '{"iban":"TEST_IBAN_001","token":"TEST_TOKEN_001"}')
        self.git("add", ".")
        self.git("commit", "-qm", "Synthetic baseline")
        self.assertEqual(self.scan()[0], 0)

    def test_ignored_export_is_never_opened(self):
        self.write(".gitignore", "*.xlsx\n")
        export = self.write("private-export.xlsx", "do not inspect")
        self.git("add", ".gitignore")
        original = checker.worktree_bytes

        def guarded(root, path):
            self.assertNotEqual(root / path, export)
            return original(root, path)

        with patch.object(checker, "worktree_bytes", side_effect=guarded):
            self.assertEqual(self.scan()[0], 0)

    def test_force_staged_export_rejected_without_opening_its_blob(self):
        self.write(".gitignore", "*.xlsx\n")
        self.write("private-export.xlsx", "TEST_PRIVATE_EXPORT_SENTINEL")
        self.git("add", ".gitignore")
        self.git("add", "-f", "private-export.xlsx")
        oid = self.git("rev-parse", ":private-export.xlsx").decode().strip()
        original = checker.git

        def guarded(root, *args):
            self.assertNotEqual(args, ("cat-file", "blob", oid))
            return original(root, *args)

        with patch.object(checker, "git", side_effect=guarded):
            status, output, _ = self.scan()
        self.assertEqual(status, 1)
        self.assertIn("private-file", output)
        self.assertNotIn("TEST_PRIVATE_EXPORT_SENTINEL", output)

    def test_staged_secret_detected_even_if_worktree_is_clean(self):
        payload = "ghp_" + "aB12" * 10
        self.write("config.txt", "provider=" + payload)
        self.git("add", "config.txt")
        self.write("config.txt", "provider=TEST_PROVIDER")
        status, output, _ = self.scan()
        self.assertEqual(status, 1)
        self.assertIn("provider-token", output)
        self.assertNotIn(payload, output)

    def test_deleted_history_secret_and_export_are_still_rejected(self):
        payload = "SECRET_KEY=" + "q7Wp9Lm3N8r6" * 3
        self.write("old.txt", payload)
        self.write("old.csv", "TEST_EXPORT")
        self.git("add", ".")
        self.git("commit", "-qm", "Old synthetic sensitive content")
        self.git("rm", "old.txt", "old.csv")
        self.git("commit", "-qm", "Delete files")
        status, output, _ = self.scan()
        self.assertEqual(status, 1)
        self.assertIn("old.txt", output)
        self.assertIn("old.csv", output)
        self.assertIn("secret-assignment", output)
        self.assertNotIn(payload, output)

    def test_dangling_blob_is_scanned(self):
        payload = "sk-" + "Ab9cD1" * 8
        subprocess.run(
            ["git", "-C", str(self.root), "hash-object", "-w", "--stdin"],
            input=payload.encode(), check=True, stdout=subprocess.PIPE,
        )
        status, output, _ = self.scan()
        self.assertEqual(status, 1)
        self.assertIn("<unreferenced-blob>", output)
        self.assertNotIn(payload, output)

    def test_iban_has_no_example_or_test_line_bypass(self):
        # Construct at runtime so this test source never contains an IBAN.
        iban = "DE" + "89" + "3704" + "0044" + "0532" + "0130" + "00"
        for value in (iban, "TEST " + iban, " ".join([iban[:4], iban[4:8], iban[8:12], iban[12:16], iban[16:20], iban[20:]])):
            with self.subTest(value_length=len(value)):
                self.assertIn("iban-like", checker.content_rules(value.encode()))
        self.assertFalse(checker.content_rules(b"TEST_IBAN_001"))

    def test_env_example_does_not_exempt_real_secret(self):
        self.write(".env.example", "AI_API_KEY=" + "reallyNotAPublicPlaceholder123456")
        self.git("add", ".env.example")
        self.assertEqual(self.scan()[0], 1)

    def test_env_url_templates_and_unsafe_defaults(self):
        template = "postgresql://finsight:${POSTGRES_PASSWORD}@db/finsight"
        self.assertFalse(checker.content_rules(template.encode()))
        self.assertFalse(checker.content_rules(b"POSTGRES_PASSWORD=${POSTGRES_PASSWORD:?Set it locally}"))
        self.assertFalse(checker.content_rules(b"POSTGRES_PASSWORD=${POSTGRES_PASSWORD:-TEST_PASSWORD}"))
        default = "not-a-synthetic-placeholder123"
        self.assertIn("secret-assignment", checker.content_rules(
            ("POSTGRES_PASSWORD=${POSTGRES_PASSWORD:-" + default + "}").encode(),
        ))
        self.assertIn("credential-url", checker.content_rules(
            template.replace("${POSTGRES_PASSWORD}", default).encode(),
        ))

    def test_exact_secure_references_quoted_and_unquoted(self):
        for value in ("${{ secrets.GITHUB_TOKEN }}", "${{secrets.TEST_TOKEN_1}}",
                      "$(openssl rand -hex 32)"):
            for quote in ("", '"', "'"):
                with self.subTest(value=value, quote=quote):
                    line = "FINSIGHT_BOOTSTRAP_SECRET=" + quote + value + quote
                    self.assertFalse(checker.content_rules(line.encode()))
        workflow_line = "GITHUB_TOKEN" + ": " + "${{ secrets.GITHUB_TOKEN }}"
        self.write(".github/workflows/ci.yml", "env:\n  " + workflow_line + "\n")
        self.write("docs/development.md", 'FINSIGHT_BOOTSTRAP_SECRET="$(openssl rand -hex 32)"\n')
        self.git("add", ".")
        self.git("commit", "-qm", "Secure nonliteral references")
        self.assertEqual(self.scan()[0], 0)

    def test_secure_reference_lookalikes_literals_and_defaults_are_blocked(self):
        values = (
            "ordinary-insecure-password",
            "${{ secrets.GITHUB_TOKEN || 'ordinary-insecure-password' }}",
            "${{ secrets.GITHUB_TOKEN }}ordinary-insecure-password",
            "${{ secrets.GITHUB_TOKEN }} ordinary-insecure-password",
            "${{ secrets.GITHUB_TOKEN }}${{ secrets.OTHER_TOKEN }}",
            "${{ env.GITHUB_TOKEN }}", "${{ secrets['GITHUB_TOKEN'] }}",
            "${TOKEN:-ordinary-insecure-password}",
            "$(openssl rand -hex 0)", "$(openssl rand -hex -1)",
            "$(openssl rand -hex 32; printf ordinary-insecure-password)",
            "$(openssl rand -hex 32)ordinary-insecure-password",
            "$(printf ordinary-insecure-password)",
        )
        for value in values:
            for quote in ("", '"'):
                with self.subTest(value=value, quote=quote):
                    line = "FINSIGHT_BOOTSTRAP_SECRET=" + quote + value + quote
                    self.assertIn("secret-assignment", checker.content_rules(line.encode()))
        for value in ('"${{ secrets.GITHUB_TOKEN }}" + "ordinary-insecure-password"',
                      '"$(openssl rand -hex 32)"ordinary-insecure-password'):
            self.assertIn("secret-assignment", checker.content_rules(("GITHUB_TOKEN=" + value).encode()))

    def test_ternary_string_alternatives_are_not_quoted_object_keys(self):
        for spacing in (" ", "\n  ", ""):
            for quote in ("'", '"'):
                expression = ("autoComplete={setup ?" + spacing + quote + "new-password" + quote
                              + " : " + quote + "current-password" + quote + "}")
                self.assertFalse(checker.content_rules(expression.encode()))

    def test_password_literals_and_objects_in_ternaries_remain_blocked(self):
        literal = "'current-password'"
        for expression in (
            "password=" + literal,
            "{" + "password:" + literal + "}",
            "{" + "'password':" + literal + "}",
            "setup ? {" + "password:" + literal + "} : {}",
            "setup ? { " + "'password':" + literal + " } : {}",
            "setup ? {\n" + '"password":' + literal + "\n} : {}",
        ):
            with self.subTest(expression=expression):
                self.assertIn("secret-assignment", checker.content_rules(expression.encode()))

    def test_checker_own_files_are_not_exempted_or_false_positive(self):
        for path in (SCRIPT, Path(__file__)):
            with self.subTest(path=path.name):
                self.assertFalse(checker.content_rules(path.read_bytes()))

    def test_forbidden_paths(self):
        for path in (".env", "app/.env.production", "production.env", "EXPORT.XLSX", "a.csv", "data/state.json", "backups/a", "a.sqlite3-wal", "app/.env.local"):
            with self.subTest(path=path):
                self.assertIsNotNone(checker.path_rule(path))
        self.assertIsNone(checker.path_rule(".env.example"))

    def test_worktree_change_and_symlink_do_not_escape(self):
        self.write("safe.txt", "TEST_ONLY")
        self.git("add", "safe.txt")
        self.write("safe.txt", "-----BEGIN " + "RSA PRIVATE KEY-----")
        self.assertEqual(self.scan()[0], 1)
        (self.root / "safe.txt").unlink()
        (self.root / "safe.txt").symlink_to("/etc/passwd")
        status, output, _ = self.scan()
        self.assertEqual(status, 1)
        self.assertIn("unreadable-working-file", output)

    def test_commit_messages_and_non_head_branches_are_scanned(self):
        self.write("safe.txt", "TEST_ONLY")
        self.git("add", ".")
        self.git("commit", "-qm", "Clean baseline")
        self.git("checkout", "-qb", "other")
        payload = "ghp_" + "z9" * 20
        self.git("commit", "--allow-empty", "-qm", payload)
        self.git("checkout", "-")
        status, output, _ = self.scan()
        self.assertEqual(status, 1)
        self.assertIn("<commit-metadata>", output)
        self.assertNotIn(payload, output)

    def test_no_repo_and_shallow_repo_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            with redirect_stdout(io.StringIO()):
                self.assertEqual(checker.main(["--repo", directory]), 2)
        self.write("safe.txt", "TEST_ONLY")
        self.git("add", ".")
        self.git("commit", "-qm", "Baseline")
        head = self.git("rev-parse", "HEAD").decode().strip()
        (self.root / ".git" / "shallow").write_text(head + "\n")
        self.assertEqual(self.scan()[0], 2)

    def test_output_schema_is_paths_and_rule_counts_only(self):
        self.write('odd\nname.txt', "PASSWORD=" + "not-a-placeholder-123")
        self.git("add", ".")
        status, output, lines = self.scan()
        self.assertEqual(status, 1)
        self.assertNotIn("not-a-placeholder-123", output)
        for line in lines:
            self.assertLessEqual(set(line), {"path", "rules"})
            self.assertTrue(all(isinstance(count, int) for count in line["rules"].values()))

    def test_png_requires_explicit_exact_review(self):
        review = self.stage_png(self.png())
        self.assertEqual(self.scan()[0], 1)
        self.assertEqual(self.scan("--reviewed-image", review)[0], 0)
        self.git("commit", "-qm", "Synthetic reviewed screenshot")
        self.assertEqual(self.scan("--reviewed-image", review)[0], 0)
        path = review.split("=", 1)[0]
        (self.root / path).write_bytes(self.png(b"\xff\0\0"))
        status, output, _ = self.scan("--reviewed-image", review)
        self.assertEqual(status, 1)
        self.assertIn("reviewed-image-hash", output)

    def test_staged_and_historical_png_versions_need_their_own_review(self):
        previous = self.stage_png(self.png())
        self.git("commit", "-qm", "Previous screenshot")
        current = self.stage_png(self.png(b"\xff\0\0"))
        self.git("commit", "-qm", "Current screenshot")
        status, output, _ = self.scan("--reviewed-image", current)
        self.assertEqual(status, 1)
        self.assertIn("reviewed-image-hash", output)
        self.assertEqual(self.scan("--reviewed-image", previous, "--reviewed-image", current)[0], 0)
        # A clean/reviewed worktree never masks an unreviewed staged version.
        self.stage_png(self.png(b"\0\xff\0"))
        (self.root / "docs/screenshots/dashboard.png").write_bytes(self.png())
        self.assertEqual(self.scan("--reviewed-image", previous, "--reviewed-image", current)[0], 1)

    def test_hash_review_does_not_transfer_to_another_path(self):
        data = self.png()
        review = self.stage_png(data)
        self.stage_png(data, "docs/screenshots/not-reviewed.png")
        status, output, _ = self.scan("--reviewed-image", review)
        self.assertEqual(status, 1)
        self.assertIn("not-reviewed.png", output)

    def test_reviewed_png_cannot_bypass_secrets_or_metadata_checks(self):
        payload = "ghp_" + "A7b2" * 10
        review = self.stage_png(self.png(metadata=payload.encode()))
        status, output, _ = self.scan("--reviewed-image", review)
        self.assertEqual(status, 1)
        self.assertIn("provider-token", output)
        self.assertIn("reviewed-image-metadata", output)
        self.assertNotIn(payload, output)

    def test_png_signature_container_crc_size_and_hash_fail_closed(self):
        image = self.png()
        for data in (b"TEST not a PNG", checker.PNG_SIGNATURE, image[:-1], image + b"extra",
                     image[:40] + bytes([image[40] ^ 1]) + image[41:]):
            with self.subTest(size=len(data)):
                self.assertIn("reviewed-image-format", checker.image_rules(
                    data, {hashlib.sha256(data).hexdigest()},
                ))
        with patch.object(checker, "MAX_IMAGE_BYTES", len(image) - 1):
            self.assertIn("reviewed-image-size", checker.image_rules(image, {hashlib.sha256(image).hexdigest()}))
        self.assertIn("reviewed-image-hash", checker.image_rules(image, {"0" * 64}))

    def test_review_parameters_reject_paths_and_malformed_hashes(self):
        for specification in ("image.png=" + "0" * 64,
                              "docs/screenshots/../other.png=" + "0" * 64,
                              "docs/screenshots/nested/image.png=" + "0" * 64,
                              "docs/screenshots/image.jpg=" + "0" * 64,
                              "docs/screenshots/image.png=not-a-hash", "missing-equals"):
            with self.subTest(specification=specification):
                self.assertEqual(self.scan("--reviewed-image", specification)[0], 2)

    def test_manifest_is_explicit_and_requires_synthetic_manual_review(self):
        review = self.stage_png(self.png())
        document = self.manifest(review)
        self.assertEqual(self.scan()[0], 1)
        self.assertEqual(self.scan("--reviewed-images", checker.REVIEW_MANIFEST)[0], 0)
        for changes in ({"synthetic_only": False}, {"synthetic_only": 1}, {"manual_review": " "},
                        {"manual_review": None}, {"images": []}, {"unexpected": True}):
            self.write(checker.REVIEW_MANIFEST, json.dumps(document | changes))
            self.assertEqual(self.scan("--reviewed-images", checker.REVIEW_MANIFEST)[0], 2)

    def test_manifest_missing_invalid_duplicate_keys_and_symlink_fail_closed(self):
        self.assertEqual(self.scan("--reviewed-images", checker.REVIEW_MANIFEST)[0], 2)
        self.assertEqual(self.scan("--reviewed-images", "elsewhere.json")[0], 2)
        for text in ("{", "null", '{"synthetic_only":true,"synthetic_only":true}'):
            self.write(checker.REVIEW_MANIFEST, text)
            self.assertEqual(self.scan("--reviewed-images", checker.REVIEW_MANIFEST)[0], 2)
        manifest = self.root / checker.REVIEW_MANIFEST
        manifest.unlink()
        manifest.symlink_to("/etc/passwd")
        self.assertEqual(self.scan("--reviewed-images", checker.REVIEW_MANIFEST)[0], 2)

    def test_synthetic_password_markers_do_not_exempt_test_files(self):
        document = {"password": "TEST_PASSWORD_001"}
        self.write("tests/fixture.json", json.dumps(document))
        self.git("add", ".")
        self.assertEqual(self.scan()[0], 0)
        document["password"] = "ordinary-insecure-password"
        self.write("tests/fixture.json", json.dumps(document))
        self.git("add", ".")
        self.assertEqual(self.scan()[0], 1)


if __name__ == "__main__":
    unittest.main()
