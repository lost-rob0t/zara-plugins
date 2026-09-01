import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_persona_service.prolog import PersonaPrologError, load_prolog_context


class PersonaPrologTest(unittest.TestCase):
    def _fake_swipl(self, directory: str, body: str) -> Path:
        path = Path(directory) / "swipl"
        path.write_text("#!/usr/bin/env python3\n" + body, encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
        return path

    def test_reads_context_from_fixed_runner(self):
        with tempfile.TemporaryDirectory() as directory:
            swipl = self._fake_swipl(
                directory,
                "import sys\nsys.stdout.write('configured context')\n",
            )
            source = Path(directory) / "persona.pl"
            source.write_text("", encoding="utf-8")
            result = load_prolog_context(
                swipl_program=str(swipl),
                prolog_file=source,
                timeout_seconds=1.0,
                output_limit=1024,
            )
            self.assertEqual(result, "configured context")

    def test_rejects_oversized_output(self):
        with tempfile.TemporaryDirectory() as directory:
            swipl = self._fake_swipl(
                directory,
                "import sys\nsys.stdout.write('x' * 32)\n",
            )
            source = Path(directory) / "persona.pl"
            source.write_text("", encoding="utf-8")
            with self.assertRaisesRegex(PersonaPrologError, "output exceeded"):
                load_prolog_context(
                    swipl_program=str(swipl),
                    prolog_file=source,
                    timeout_seconds=1.0,
                    output_limit=16,
                )

    def test_missing_swipl_is_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "persona.pl"
            source.write_text("", encoding="utf-8")
            with self.assertRaisesRegex(PersonaPrologError, "executable not found"):
                load_prolog_context(
                    swipl_program=str(Path(directory) / "missing-swipl"),
                    prolog_file=source,
                    timeout_seconds=1.0,
                    output_limit=1024,
                )


if __name__ == "__main__":
    unittest.main()
