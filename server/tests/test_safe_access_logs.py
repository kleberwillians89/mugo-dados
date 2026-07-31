import io
import logging
import sys
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import AsyncMock
from pathlib import Path

SERVER_DIR = str(Path(__file__).parents[1])
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

import app as app_module


class SafeAccessLogTests(unittest.IsolatedAsyncioTestCase):
    async def test_callback_log_uses_path_only_and_never_secrets(self):
        request = SimpleNamespace(
            method="GET",
            headers={},
            url=SimpleNamespace(
                path="/api/oauth/google/callback",
                query="code=secret-code&state=secret-state&access_token=secret-token",
            ),
        )
        response = SimpleNamespace(status_code=302, headers={})
        output = io.StringIO()
        with redirect_stdout(output):
            result = await app_module.safe_request_log(
                request,
                AsyncMock(return_value=response),
            )
        log = output.getvalue()
        self.assertIs(result, response)
        self.assertIn("path=/api/oauth/google/callback", log)
        self.assertIn("provider=google", log)
        for secret in ("secret-code", "secret-state", "secret-token", "access_token", "state="):
            self.assertNotIn(secret, log)

    def test_uvicorn_default_access_logger_is_disabled(self):
        self.assertTrue(logging.getLogger("uvicorn.access").disabled)
