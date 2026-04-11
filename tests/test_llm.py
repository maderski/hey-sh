import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.modules.setdefault(
    "httpx",
    SimpleNamespace(
        Client=None,
        ConnectError=Exception,
        TimeoutException=Exception,
        HTTPStatusError=Exception,
    ),
)

from hey import llm


class FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200, text: str = "ok") -> None:
        self._payload = payload
        self.status_code = status_code
        self.text = text

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class FakeHttpStatusError(Exception):
    def __init__(self, response: FakeResponse) -> None:
        super().__init__("http error")
        self.response = response


class RecordingClient:
    def __init__(self, response: FakeResponse, calls: list[dict], timeout: float) -> None:
        self._response = response
        self._calls = calls
        self._timeout = timeout

    def __enter__(self) -> "RecordingClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def post(self, endpoint: str, json: dict) -> FakeResponse:
        self._calls.append({"endpoint": endpoint, "json": json, "timeout": self._timeout})
        return self._response


class TestLlm(unittest.TestCase):
    def test_query_llm_returns_message_and_builds_expected_payload(self) -> None:
        calls: list[dict] = []

        def fake_client(timeout: float) -> RecordingClient:
            response = FakeResponse(
                {
                    "choices": [
                        {
                            "message": {
                                "content": "ls -la",
                            }
                        }
                    ]
                }
            )
            return RecordingClient(response, calls, timeout)

        fake_httpx = SimpleNamespace(Client=fake_client)

        with patch.object(llm, "httpx", fake_httpx):
            result = llm.query_llm(
                prompt="list files",
                explain=True,
                shell="zsh",
                platform="macOS",
                endpoint="http://localhost:8080/v1/chat/completions",
                model="local",
            )

        self.assertEqual(result, "ls -la")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["endpoint"], "http://localhost:8080/v1/chat/completions")
        self.assertEqual(calls[0]["timeout"], 30.0)
        self.assertEqual(calls[0]["json"]["model"], "local")
        self.assertEqual(calls[0]["json"]["messages"][1]["content"], "list files")
        self.assertIn("The user's shell is zsh. The user's OS is macOS.", calls[0]["json"]["messages"][0]["content"])

    def test_ping_llm_reports_success(self) -> None:
        calls: list[dict] = []

        def fake_client(timeout: float) -> RecordingClient:
            response = FakeResponse({"model": "llama3"})
            return RecordingClient(response, calls, timeout)

        fake_httpx = SimpleNamespace(
            Client=fake_client,
            ConnectError=type("ConnectError", (Exception,), {}),
            TimeoutException=type("TimeoutException", (Exception,), {}),
            HTTPStatusError=FakeHttpStatusError,
        )

        with patch.object(llm, "httpx", fake_httpx), patch("hey.llm.time.monotonic", side_effect=[10.0, 10.25]):
            result = llm.ping_llm("http://localhost:8080/v1/chat/completions", "local")

        self.assertTrue(result["ok"])
        self.assertEqual(result["elapsed_ms"], 250)
        self.assertEqual(result["model"], "llama3")
        self.assertEqual(calls[0]["timeout"], 10.0)

    def test_ping_llm_handles_connect_error(self) -> None:
        connect_error = type("ConnectError", (Exception,), {})

        class FailingClient:
            def __init__(self, timeout: float) -> None:
                self.timeout = timeout

            def __enter__(self) -> "FailingClient":
                return self

            def __exit__(self, exc_type, exc, tb) -> bool:
                return False

            def post(self, endpoint: str, json: dict) -> FakeResponse:
                raise connect_error()

        fake_httpx = SimpleNamespace(
            Client=FailingClient,
            ConnectError=connect_error,
            TimeoutException=type("TimeoutException", (Exception,), {}),
            HTTPStatusError=FakeHttpStatusError,
        )

        with patch.object(llm, "httpx", fake_httpx):
            result = llm.ping_llm("http://localhost:8080/v1/chat/completions", "local")

        self.assertFalse(result["ok"])
        self.assertIn("Could not connect", result["error"])

    def test_ping_llm_handles_timeout_error(self) -> None:
        timeout_error = type("TimeoutException", (Exception,), {})

        class TimingOutClient:
            def __init__(self, timeout: float) -> None:
                self.timeout = timeout

            def __enter__(self) -> "TimingOutClient":
                return self

            def __exit__(self, exc_type, exc, tb) -> bool:
                return False

            def post(self, endpoint: str, json: dict) -> FakeResponse:
                raise timeout_error()

        fake_httpx = SimpleNamespace(
            Client=TimingOutClient,
            ConnectError=type("ConnectError", (Exception,), {}),
            TimeoutException=timeout_error,
            HTTPStatusError=FakeHttpStatusError,
        )

        with patch.object(llm, "httpx", fake_httpx):
            result = llm.ping_llm("http://localhost:8080/v1/chat/completions", "local")

        self.assertFalse(result["ok"])
        self.assertIn("timed out", result["error"])

    def test_ping_llm_handles_generic_exception(self) -> None:
        class BrokenClient:
            def __init__(self, timeout: float) -> None:
                self.timeout = timeout

            def __enter__(self) -> "BrokenClient":
                return self

            def __exit__(self, exc_type, exc, tb) -> bool:
                return False

            def post(self, endpoint: str, json: dict) -> FakeResponse:
                raise ValueError("unexpected failure")

        fake_httpx = SimpleNamespace(
            Client=BrokenClient,
            ConnectError=type("ConnectError", (Exception,), {}),
            TimeoutException=type("TimeoutException", (Exception,), {}),
            HTTPStatusError=FakeHttpStatusError,
        )

        with patch.object(llm, "httpx", fake_httpx):
            result = llm.ping_llm("http://localhost:8080/v1/chat/completions", "local")

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "unexpected failure")

    def test_ping_llm_handles_http_status_error(self) -> None:
        http_status_error = FakeHttpStatusError

        class FailingResponse(FakeResponse):
            def raise_for_status(self) -> None:
                raise http_status_error(self)

        class FailingClient:
            def __init__(self, timeout: float) -> None:
                self.timeout = timeout

            def __enter__(self) -> "FailingClient":
                return self

            def __exit__(self, exc_type, exc, tb) -> bool:
                return False

            def post(self, endpoint: str, json: dict) -> FakeResponse:
                return FailingResponse({}, status_code=503, text="service unavailable")

        fake_httpx = SimpleNamespace(
            Client=FailingClient,
            ConnectError=type("ConnectError", (Exception,), {}),
            TimeoutException=type("TimeoutException", (Exception,), {}),
            HTTPStatusError=http_status_error,
        )

        with patch.object(llm, "httpx", fake_httpx):
            result = llm.ping_llm("http://localhost:8080/v1/chat/completions", "local")

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "HTTP 503: service unavailable")
