#!/usr/bin/env python3
"""Offline regression tests for the SModelS installer's integrity boundaries."""

import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import zipfile

spec = importlib.util.spec_from_file_location("toolchain", Path(__file__).with_name("smodels-toolchain.py"))
toolchain = importlib.util.module_from_spec(spec)
spec.loader.exec_module(toolchain)
verification_spec = importlib.util.spec_from_file_location("verification", Path(__file__).with_name("verify-smodels.py"))
verification = importlib.util.module_from_spec(verification_spec)
verification_spec.loader.exec_module(verification)


class IntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_both_source_checksums_gate_extraction(self):
        archive = self.root / "source.tgz"
        archive.write_bytes(b"source fixture")
        source = {key: toolchain.digest(archive, key) for key in ("md5", "sha256")}
        with patch.multiple(toolchain, ARCHIVE=archive, SPEC={"source": source}):
            toolchain.check_source()
            for key in ("md5", "sha256"):
                with self.subTest(algorithm=key), patch.dict(source, {key: "wrong"}):
                    with patch.object(toolchain, "extract") as extract:
                        with self.assertRaisesRegex(RuntimeError, key + " mismatch"):
                            toolchain.prepare()
                        extract.assert_not_called()

    def test_zip_rejects_path_traversal(self):
        archive = self.root / "unsafe.zip"
        with zipfile.ZipFile(archive, "w") as handle:
            handle.writestr("../escaped", "not allowed")
        with self.assertRaisesRegex(RuntimeError, "Unsafe ZIP"):
            toolchain.extract(archive, self.root / "extracted")
        self.assertFalse((self.root / "escaped").exists())

    def test_tar_rejects_path_traversal(self):
        archive = self.root / "unsafe.tar.gz"
        with tarfile.open(archive, "w:gz") as handle:
            entry = tarfile.TarInfo("../escaped")
            entry.size = 1
            handle.addfile(entry, io.BytesIO(b"x"))
        with self.assertRaises(tarfile.FilterError):
            toolchain.extract(archive, self.root / "extracted")
        self.assertFalse((self.root / "escaped").exists())

    def test_zip_restores_executable_mode(self):
        archive = self.root / "source.zip"
        with zipfile.ZipFile(archive, "w") as handle:
            entry = zipfile.ZipInfo("configure")
            entry.external_attr = 0o100755 << 16
            handle.writestr(entry, "#!/bin/sh\nexit 0\n")
        destination = self.root / "extracted"
        toolchain.extract(archive, destination)
        self.assertEqual((destination / "configure").stat().st_mode & 0o777, 0o755)

    def test_case_distinct_translation_units_survive(self):
        archive = self.root / "source.zip"
        with zipfile.ZipFile(archive, "w") as handle:
            handle.writestr("QQ.cc", "upper")
            handle.writestr("qq.cc", "lower")
        destination = self.root / "extracted"
        toolchain.extract(archive, destination)
        mappings = toolchain.restore_case_collisions(archive, destination)
        upper = destination / mappings.get("QQ.cc", "QQ.cc")
        self.assertEqual(upper.read_text(), "upper")
        self.assertEqual((destination / "qq.cc").read_text(), "lower")
        self.assertEqual(mappings, toolchain.restore_case_collisions(archive, destination))

    def test_provenance_rejects_modified_binaries_and_missing_downloads(self):
        executable = self.root / "program"
        executable.write_bytes(b"native executable fixture")
        executable.chmod(0o755)
        download = self.root / "download"
        download.write_bytes(b"download fixture")
        marker = self.root / "PROVENANCE.json"
        info = {"version": toolchain.VERSION, "source": toolchain.SPEC["source"],
                "external_tools": toolchain.SPEC["external_tools"],
                "patches": {toolchain.RESUMMINO_PATCH.name: toolchain.digest(toolchain.RESUMMINO_PATCH)},
                "binaries": {"program": toolchain.digest(executable)},
                "downloads": {"download": {"url": "https://example.invalid/source",
                                              "sha256": toolchain.digest(download)}}}
        marker.write_text(json.dumps(info))
        with patch.multiple(toolchain, MARKER=marker, LIB=self.root, CACHE=self.root,
                            BINARIES=["program"], DOWNLOAD_URLS={"download": "https://example.invalid/source"}):
            toolchain.check_bundle()
            executable.write_bytes(b"modified")
            with self.assertRaisesRegex(RuntimeError, "changed external executable"):
                toolchain.check_bundle()
            info["binaries"]["program"] = toolchain.digest(executable)
            info["downloads"] = {}
            marker.write_text(json.dumps(info))
            with self.assertRaisesRegex(RuntimeError, "Incomplete external download provenance"):
                toolchain.check_bundle()


class DatabaseOptInTests(unittest.TestCase):
    def setUp(self):
        # Routing tests mock execution; do not print simulated validation reports.
        output = patch.object(verification.sys, "stdout", io.StringIO())
        output.start()
        self.addCleanup(output.stop)

    def test_default_never_prepares_database(self):
        with patch.object(verification, "installation_checks") as checks, \
                patch.object(verification, "prepare_database", side_effect=AssertionError("unexpected database access")), \
                patch.object(verification, "idm_validation") as idm:
            verification.main()
            checks.assert_called_once()
            idm.assert_not_called()

    def test_native_never_prepares_database(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(verification, "ROOT", Path(directory)), \
                patch.object(verification, "installation_checks"), \
                patch.object(verification, "prepare_database", side_effect=AssertionError("unexpected database access")), \
                patch.object(verification, "idm_validation") as idm, \
                patch.object(verification.subprocess, "run") as run:
            verification.main(native=True)
            idm.assert_not_called()
            run.assert_called_once()
            self.assertIn("--native-worker", run.call_args.args[0])

    def test_database_requires_explicit_opt_in(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(verification, "ROOT", Path(directory)), \
                patch.object(verification, "installation_checks"), \
                patch.object(verification, "idm_validation", return_value={}) as idm:
            verification.main(idm_database=True)
            idm.assert_called_once()


if __name__ == "__main__":
    unittest.main()
