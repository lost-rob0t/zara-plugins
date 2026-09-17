from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
from zara_prolog.session import PrologSession, PrologSessionError


def _production_bridge_available() -> bool:
    return (
        importlib.util.find_spec("pyswip") is not None
        and importlib.util.find_spec("zara.prolog_engine") is not None
    )


class RealPrologLifecycleTests(unittest.TestCase):
    def test_real_engine_start_query_stop_restart_and_reload(self):
        required = os.environ.get("ZARA_REQUIRE_SWIPL") == "1"
        if not _production_bridge_available():
            if required:
                self.fail(
                    "native gate requires the real Zara PrologEngine/PySWIP bridge; "
                    "direct swipl-only evidence is insufficient"
                )
            self.skipTest("real Zara PrologEngine/PySWIP bridge unavailable")

        with tempfile.TemporaryDirectory() as directory:
            config_root = Path(directory)
            session = PrologSession(config_root)
            try:
                session.start()
                self.assertTrue(session.ready)
                first = session.query("prolog_mode(Mode)")
                self.assertEqual(first["status"], "success")
                self.assertEqual(first["solutions"], [{"Mode": "symbolic"}])
                self.assertEqual(session.reload()["status"], "reloaded")

                session.stop()
                self.assertFalse(session.ready)
                with self.assertRaises(PrologSessionError):
                    session.query("prolog_mode(Mode)")

                (config_root / "config.pl").write_text(
                    ":- module(zara_prolog_user, [prolog_mode/1]).\n"
                    "prolog_mode(restarted).\n",
                    encoding="utf-8",
                )
                session.start()
                self.assertTrue(session.ready)
                restarted = session.query("prolog_mode(Mode)")
                self.assertEqual(restarted["status"], "success")
                self.assertEqual(restarted["solutions"], [{"Mode": "restarted"}])
            finally:
                session.stop()


if __name__ == "__main__":
    unittest.main()
