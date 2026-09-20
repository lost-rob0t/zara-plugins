import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_expert.domain import ExpertError
from zara_expert.dotfiles_style import style_sources_for_language


class FakeStyleHost:
    def __init__(self, *, overrides=None):
        self.overrides = overrides or {}
        self.calls = []

    @staticmethod
    def _key(predicate, arguments):
        second = arguments[1]
        if isinstance(second, dict) and second == {"var": "Revision"}:
            second = "<Revision>"
        return predicate, arguments[0], second

    def query(self, namespace, predicate, arguments):
        self.calls.append((namespace, predicate, arguments))
        key = self._key(predicate, arguments)
        if key in self.overrides:
            return self.overrides[key]
        if key == ("style_source", "project", "any"):
            results = [
                "style_source(project,any,'.zara/style/project.pl','dotfiles-project-style-v1')"
            ]
        elif key == ("style_source", "project_language", "nix"):
            results = [
                "style_source(project_language,nix,'.zara/style/languages/nix.pl','dotfiles-nix-style-v1')"
            ]
        elif key == ("style_source", "project_language", "bash"):
            results = [
                "style_source(project_language,bash,'.zara/style/languages/bash.pl','dotfiles-bash-style-v1')"
            ]
        elif key == ("style_revision", "project", "<Revision>"):
            results = ["style_revision(project,'dotfiles-project-style-v1')"]
        elif key == ("style_revision", "nix", "<Revision>"):
            results = ["style_revision(nix,'dotfiles-nix-style-v1')"]
        elif key == ("style_revision", "bash", "<Revision>"):
            results = ["style_revision(bash,'dotfiles-bash-style-v1')"]
        else:
            results = []
        return {"ok": True, "results": results, "trace": []}


class DotfilesStyleTests(unittest.TestCase):
    def test_nix_and_bash_resolve_only_canonical_style_sources(self):
        host = FakeStyleHost()
        nix_project, nix_language = style_sources_for_language(host, "nix")
        bash_project, bash_language = style_sources_for_language(host, "bash")

        self.assertEqual(nix_project.source_reference, ".zara/style/project.pl")
        self.assertEqual(nix_project.revision, "dotfiles-project-style-v1")
        self.assertEqual(nix_language.source_reference, ".zara/style/languages/nix.pl")
        self.assertEqual(nix_language.revision, "dotfiles-nix-style-v1")
        self.assertEqual(
            nix_language.reference,
            "style:dotfiles-nix-style-v1:.zara/style/languages/nix.pl",
        )

        self.assertEqual(bash_project, nix_project)
        self.assertEqual(bash_language.source_reference, ".zara/style/languages/bash.pl")
        self.assertEqual(bash_language.revision, "dotfiles-bash-style-v1")
        self.assertEqual(
            bash_language.reference,
            "style:dotfiles-bash-style-v1:.zara/style/languages/bash.pl",
        )
        self.assertTrue(
            all(call[0] == "dotfiles-expert" for call in host.calls),
            "style metadata must stay behind the existing registered namespace",
        )

    def test_unsupported_language_fails_before_host_dispatch(self):
        host = FakeStyleHost()
        with self.assertRaisesRegex(ExpertError, "unsupported DotfilesExpert style language"):
            style_sources_for_language(host, "python")
        self.assertEqual(host.calls, [])

    def test_malformed_or_duplicate_source_fails_closed(self):
        duplicate = FakeStyleHost(
            overrides={
                ("style_source", "project", "any"): {
                    "ok": True,
                    "results": [
                        "style_source(project,any,'.zara/style/project.pl','dotfiles-project-style-v1')",
                        "style_source(project,any,'.zara/style/other.pl','dotfiles-project-style-v1')",
                    ],
                    "trace": [],
                }
            }
        )
        with self.assertRaisesRegex(ExpertError, "exactly one result"):
            style_sources_for_language(duplicate, "nix")

        escaped = FakeStyleHost(
            overrides={
                ("style_source", "project_language", "nix"): {
                    "ok": True,
                    "results": [
                        "style_source(project_language,nix,'.zara/style/../secrets.pl','dotfiles-nix-style-v1')"
                    ],
                    "trace": [],
                }
            }
        )
        with self.assertRaisesRegex(ExpertError, "canonical .zara/style root"):
            style_sources_for_language(escaped, "nix")

    def test_revision_mismatch_fails_closed(self):
        host = FakeStyleHost(
            overrides={
                ("style_revision", "nix", "<Revision>"): {
                    "ok": True,
                    "results": ["style_revision(nix,'dotfiles-nix-style-v0')"],
                    "trace": [],
                }
            }
        )
        with self.assertRaisesRegex(ExpertError, "style source revision mismatch"):
            style_sources_for_language(host, "nix")


if __name__ == "__main__":
    unittest.main()
