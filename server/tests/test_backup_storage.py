"""Backup dos arquivos do Storage: percorre pastas, baixa tudo e não loga nomes."""
import importlib.util
import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import httpx

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("backup_storage", ROOT / ".github/scripts/backup_storage.py")
bs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bs)

TREE = {"ig-media": {"": [{"name": "cliente-a", "id": None}, {"name": "logo.png", "id": "1"}],
                     "cliente-a/": [{"name": "arte.jpg", "id": "2"}]}}


def handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path.endswith("/bucket"):
        return httpx.Response(200, json=[{"id": "ig-media"}])
    if "/object/list/" in path:
        import json
        prefix = json.loads(request.content)["prefix"]
        return httpx.Response(200, json=TREE["ig-media"].get(prefix, []))
    if "/object/authenticated/" in path:
        return httpx.Response(200, content=b"conteudo-" + path.rsplit("/", 1)[-1].encode())
    return httpx.Response(404)


class BackupStorageTests(unittest.TestCase):
    def test_downloads_every_file_recursively_and_logs_only_totals(self):
        client = httpx.Client(base_url="https://x.supabase.co/storage/v1", transport=httpx.MockTransport(handler))
        with tempfile.TemporaryDirectory() as tmp, patch.object(bs, "_client", return_value=client), \
             patch.object(sys, "argv", ["backup_storage.py", tmp]):
            out = io.StringIO()
            with redirect_stdout(out):
                code = bs.main()
            self.assertEqual(code, 0)
            self.assertEqual((Path(tmp) / "ig-media/cliente-a/arte.jpg").read_bytes(), b"conteudo-arte.jpg")
            self.assertTrue((Path(tmp) / "ig-media/logo.png").exists())
        log = out.getvalue()
        self.assertIn("arquivos=2", log)
        self.assertNotIn("arte.jpg", log)   # log público: sem nome de arquivo


if __name__ == "__main__":
    unittest.main()
