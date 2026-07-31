import io
import logging
import sys
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import AsyncMock
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, Response, StreamingResponse

SERVER_DIR = str(Path(__file__).parents[1])
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

import app as app_module


class SafeAccessLogTests(unittest.IsolatedAsyncioTestCase):
    async def test_204_response_has_no_body_or_content_length_mismatch(self):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app_module.app),
            base_url="http://testserver",
        ) as client:
            response = await client.get("/favicon.ico")
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.content, b"")
        self.assertNotIn("content-length", response.headers)

    async def test_json_head_options_and_errors_have_consistent_content_length(self):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app_module.app, raise_app_exceptions=False),
            base_url="http://testserver",
        ) as client:
            responses = [
                await client.get("/health"),
                await client.head("/"),
                await client.options(
                    "/health",
                    headers={
                        "Origin": "http://localhost:5173",
                        "Access-Control-Request-Method": "GET",
                    },
                ),
                await client.get("/api/connections"),
            ]
        self.assertEqual([item.status_code for item in responses], [200, 200, 200, 401])
        self.assertEqual(responses[1].content, b"")
        for response in (responses[0], responses[2], responses[3]):
            declared = response.headers.get("content-length")
            if declared is not None:
                self.assertEqual(int(declared), len(response.content))

    async def test_middleware_preserves_redirect_errors_and_streaming_lengths(self):
        mini = FastAPI()
        mini.middleware("http")(app_module.safe_request_log)
        mini.add_middleware(
            CORSMiddleware,
            allow_origins=["https://dados.mugoagencia.com.br"],
            allow_methods=["*"],
            allow_headers=["*"],
        )

        mini.add_api_route("/redirect", lambda: RedirectResponse("/target", status_code=302))
        mini.add_api_route("/empty", lambda: Response(status_code=204))
        for status in (401, 403, 409, 500):
            mini.add_api_route(
                f"/error-{status}",
                lambda status=status: JSONResponse({"status": status}, status_code=status),
            )

        async def chunks():
            yield b"one"
            yield b"two"

        mini.add_api_route("/stream", lambda: StreamingResponse(chunks(), media_type="text/plain"))

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=mini, raise_app_exceptions=False),
            base_url="http://testserver",
            follow_redirects=False,
        ) as client:
            responses = [await client.get("/redirect")]
            responses.extend([await client.get(f"/error-{status}") for status in (401, 403, 409, 500)])
            responses.extend(
                [
                    await client.get("/empty"),
                    await client.get("/stream"),
                    await client.options(
                        "/stream",
                        headers={
                            "Origin": "https://dados.mugoagencia.com.br",
                            "Access-Control-Request-Method": "GET",
                        },
                    ),
                ]
            )
        self.assertEqual([item.status_code for item in responses], [302, 401, 403, 409, 500, 204, 200, 200])
        self.assertEqual(responses[5].content, b"")
        self.assertEqual(responses[6].content, b"onetwo")
        for response in responses:
            declared = response.headers.get("content-length")
            if declared is not None:
                self.assertEqual(int(declared), len(response.content))

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
        self.assertIn("integration_product=-", log)
        for secret in ("secret-code", "secret-state", "secret-token", "access_token", "state="):
            self.assertNotIn(secret, log)

    def test_uvicorn_default_access_logger_is_disabled(self):
        self.assertTrue(logging.getLogger("uvicorn.access").disabled)
