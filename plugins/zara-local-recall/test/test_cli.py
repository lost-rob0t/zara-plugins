"""Deterministic tests for the bounded CLI bridge."""

import unittest
from dataclasses import dataclass

from local_recall_test_support import LIB_ROOT  # noqa: F401

from zara_local_recall_service import cli
from zara_local_recall_service.paths import PluginSettings


@dataclass(frozen=True)
class Completed:
    returncode: int
    stdout: bytes


SETTINGS = PluginSettings()


def captured(commands_responses: dict[tuple[str, ...], Completed]):
    def runner(command, capture_output, timeout):
        key = tuple(command)
        if key not in commands_responses:
            raise AssertionError(f"unexpected command: {command}")
        return commands_responses[key]

    return runner


class CliBridgeTests(unittest.TestCase):
    def test_build_command_appends_json(self) -> None:
        self.assertEqual(cli.build_command(["status"]), ["local-recall", "status", "--json"])

    def test_success_response_is_parsed(self) -> None:
        result = cli.parse_output(b'{"outcome":"success","text":"off"}')
        self.assertEqual(result.outcome, "success")
        self.assertEqual(result.text, "off")
        self.assertIsNone(result.reason_code)

    def test_failure_response_is_parsed(self) -> None:
        result = cli.parse_output(b'{"outcome":"invalid","reason_code":"capture-disabled"}')
        self.assertEqual(result.outcome, "invalid")
        self.assertEqual(result.text, "")
        self.assertEqual(result.reason_code, "capture-disabled")

    def test_invalid_response_is_rejected(self) -> None:
        with self.assertRaises(RuntimeError):
            cli.parse_output(b'{"nonsense": true}')
        with self.assertRaises(RuntimeError):
            cli.parse_output(b"not json")

    def test_status_runs_bounded_command(self) -> None:
        responses = {
            ("local-recall", "status", "--json"): Completed(0, b'{"outcome":"success"}')
        }
        result = cli.status(settings=SETTINGS, runner=captured(responses))
        self.assertEqual(result.outcome, "success")

    def test_ask_requires_nonempty_query(self) -> None:
        with self.assertRaises(RuntimeError):
            cli.ask("   ", settings=SETTINGS)

    def test_ask_passes_question(self) -> None:
        seen: list[list[str]] = []

        def runner(command, capture_output, timeout):
            seen.append(list(command))
            return Completed(0, b'{"outcome":"success","text":"answer"}')

        result = cli.ask("what was I doing today?", settings=SETTINGS, runner=runner)
        self.assertEqual(result.text, "answer")
        self.assertEqual(seen[0][:2], ["local-recall", "ask"])

    def test_search_requires_bounds(self) -> None:
        with self.assertRaises(RuntimeError):
            cli.search("emacs", start="", end="", settings=SETTINGS)

    def test_unavailable_cli_maps_to_reason(self) -> None:
        def runner(command, capture_output, timeout):
            raise FileNotFoundError()

        with self.assertRaises(RuntimeError):
            cli.status(settings=SETTINGS, runner=runner)

    def test_non_contract_exit_code_is_rejected(self) -> None:
        responses = {("local-recall", "status", "--json"): Completed(1, b"{}")}
        with self.assertRaises(RuntimeError):
            cli.status(settings=SETTINGS, runner=captured(responses))


if __name__ == "__main__":
    unittest.main()
