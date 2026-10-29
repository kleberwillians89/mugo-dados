from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import studio_assets as sa
from services.studio_calendar import StudioError

A1, A2, A3 = ("aaaaaaaa-0000-0000-0000-00000000000" + str(i) for i in (1, 2, 3))
ITEM = "11111111-1111-1111-1111-111111111111"
MB = 1024 * 1024


def pending_row(**kw):
    return {"id": A1, "client_id": "roove", "storage_path": f"roove/{A1}.png", "thumb_path": f"roove/{A1}.thumb.jpg",
            "kind": "imagem", "mime_type": "image/png", "size_bytes": 1000, "name": "arte.png", "folder": None,
            "tags": [], "status": "pendente", **kw}


def fake_sign(paths, expires_in=sa.SIGNED_URL_SECONDS):
    return {p: f"https://sb/storage/v1/object/sign/studio-assets/{p}?token=t" for p in paths if p}


class ValidationTests(unittest.TestCase):
    def test_type_and_size_limits_per_kind(self):
        self.assertEqual(sa.classify("image/png", 15 * MB), ("imagem", "png"))
        self.assertEqual(sa.classify("video/quicktime", 200 * MB), ("video", "mov"))
        self.assertEqual(sa.classify("application/pdf", 30 * MB), ("pdf", "pdf"))
        for mime, size in (("image/jpeg", 15 * MB + 1), ("video/mp4", 200 * MB + 1), ("application/pdf", 30 * MB + 1)):
            with self.subTest(mime=mime), self.assertRaises(StudioError) as err:
                sa.classify(mime, size)
            self.assertEqual(err.exception.code, "FILE_TOO_LARGE")
        for mime in ("image/gif", "image/svg+xml", "text/html", "application/zip", ""):
            with self.subTest(mime=mime), self.assertRaises(StudioError) as err:
                sa.classify(mime, 10)
            self.assertEqual(err.exception.code, "TYPE_NOT_ALLOWED")
        with self.assertRaises(StudioError):
            sa.classify("image/png", 0)

    def test_magic_bytes_must_match_declared_type(self):
        self.assertTrue(sa.signature_matches("image/png", b"\x89PNG\r\n\x1a\n" + b"\0" * 8))
        self.assertTrue(sa.signature_matches("image/jpeg", b"\xff\xd8\xff\xe0"))
        self.assertTrue(sa.signature_matches("image/webp", b"RIFF\0\0\0\0WEBPVP8 "))
        self.assertTrue(sa.signature_matches("application/pdf", b"%PDF-1.7"))
        self.assertTrue(sa.signature_matches("video/mp4", b"\0\0\0\x20ftypisom"))
        self.assertTrue(sa.signature_matches("video/quicktime", b"\0\0\0\x14ftypqt  "))
        self.assertFalse(sa.signature_matches("image/png", b"<html><script>"))
        self.assertFalse(sa.signature_matches("application/pdf", b"\x89PNG\r\n\x1a\n"))
        self.assertFalse(sa.signature_matches("video/mp4", b"%PDF-1.7 aaaaaa"))

    def test_names_folders_and_tags_are_sanitized(self):
        self.assertEqual(sa.clean_name("C:\\fakepath\\..\\Arte  Natal.png"), "Arte Natal.png")
        self.assertEqual(sa.clean_name("../../etc/passwd"), "passwd")
        with self.assertRaises(StudioError):
            sa.clean_name("  /  ")
        self.assertEqual(sa.clean_folder(" Campanhas/Natal "), "Campanhas Natal")
        self.assertIsNone(sa.clean_folder("   "))
        self.assertEqual(sa.clean_tags(["#Natal", "natal", " Black  Friday ", 'x"}{']), ["natal", "black friday", "x"])


class RequestUploadTests(unittest.IsolatedAsyncioTestCase):
    async def test_creates_pending_row_and_signed_urls_inside_the_company_folder(self):
        signed = AsyncMock(side_effect=lambda path: {"path": path, "token": "tok", "signed_url": f"https://sb/{path}?token=tok"})
        with patch.object(sa, "sb_select", AsyncMock(return_value=[])), \
             patch.object(sa, "sb_insert", AsyncMock(side_effect=lambda table, row: row)) as insert, \
             patch.object(sa, "storage_sign_upload", signed):
            result = await sa.request_upload("roove", file_name="Reels Natal.MP4", mime_type="video/mp4", size_bytes=50 * MB,
                                             folder="Natal", tags=["#Natal"], with_thumb=True, user_id="u1")
        row = insert.await_args.args[1]
        self.assertEqual(row["status"], "pendente")
        self.assertRegex(row["storage_path"], r"^roove/[0-9a-f-]{36}\.mp4$")
        self.assertEqual(row["thumb_path"], row["storage_path"].replace(".mp4", ".thumb.jpg"))
        self.assertEqual((row["kind"], row["folder"], row["tags"]), ("video", "Natal", ["natal"]))
        self.assertEqual(result["upload"]["path"], row["storage_path"])
        self.assertEqual(result["thumb_upload"]["path"], row["thumb_path"])
        self.assertNotIn("storage_path", result["asset"])

    async def test_pdf_never_gets_thumbnail_and_oversized_file_is_refused_before_any_write(self):
        with patch.object(sa, "sb_select", AsyncMock(return_value=[])), \
             patch.object(sa, "sb_insert", AsyncMock(side_effect=lambda table, row: row)) as insert, \
             patch.object(sa, "storage_sign_upload", AsyncMock(return_value={"path": "p", "token": "t", "signed_url": "u"})):
            result = await sa.request_upload("roove", file_name="guia.pdf", mime_type="application/pdf", size_bytes=MB,
                                             folder=None, tags=[], with_thumb=True, user_id="u1")
            self.assertIsNone(result["thumb_upload"])
            insert.reset_mock()
            with self.assertRaises(StudioError):
                await sa.request_upload("roove", file_name="x.png", mime_type="image/png", size_bytes=16 * MB,
                                        folder=None, tags=[], with_thumb=False, user_id="u1")
            insert.assert_not_awaited()

    async def test_signing_failure_removes_the_pending_row(self):
        with patch.object(sa, "sb_select", AsyncMock(return_value=[])), \
             patch.object(sa, "sb_insert", AsyncMock(side_effect=lambda table, row: row)), \
             patch.object(sa, "sb_delete", AsyncMock(return_value=[{}])) as delete, \
             patch.object(sa, "storage_sign_upload", AsyncMock(side_effect=StudioError("STORAGE_ERROR"))):
            with self.assertRaises(StudioError):
                await sa.request_upload("roove", file_name="a.png", mime_type="image/png", size_bytes=10,
                                        folder=None, tags=[], with_thumb=False, user_id="u1")
        self.assertEqual(delete.await_args.kwargs["filters"]["client_id"], "eq.roove")

    async def test_too_many_pending_uploads_are_throttled(self):
        with patch.object(sa, "sb_select", AsyncMock(return_value=[{}] * sa.MAX_PENDING_PER_HOUR)), \
             patch.object(sa, "sb_insert", AsyncMock()) as insert:
            with self.assertRaises(StudioError) as err:
                await sa.request_upload("roove", file_name="a.png", mime_type="image/png", size_bytes=10,
                                        folder=None, tags=[], with_thumb=False, user_id="u1")
        self.assertEqual(err.exception.code, "TOO_MANY_PENDING")
        insert.assert_not_awaited()


class ConfirmUploadTests(unittest.IsolatedAsyncioTestCase):
    def patches(self, row, infos, head=b"\x89PNG\r\n\x1a\n"):
        return (
            patch.object(sa, "sb_select", AsyncMock(return_value=[row])),
            patch.object(sa, "storage_object_info", AsyncMock(side_effect=infos)),
            patch.object(sa, "storage_read_head", AsyncMock(return_value=head)),
            patch.object(sa, "storage_sign_urls", AsyncMock(side_effect=fake_sign)),
            patch.object(sa, "storage_remove", AsyncMock()),
            patch.object(sa, "sb_update", AsyncMock(side_effect=lambda table, filters, patch: [{**row, **patch}])),
            patch.object(sa, "sb_delete", AsyncMock(return_value=[{}])),
        )

    async def test_real_object_metadata_promotes_to_ready(self):
        p = self.patches(pending_row(), [{"size": 4321, "mimetype": "image/png"}, {"size": 9000, "mimetype": "image/jpeg"}])
        with p[0], p[1], p[2], p[3], p[4], p[5] as update, p[6]:
            asset = await sa.confirm_upload("roove", A1, width=1080, height=1350, duration_seconds=None)
        patch_sent = update.await_args.kwargs["patch"]
        self.assertEqual((patch_sent["status"], patch_sent["size_bytes"], patch_sent["width"]), ("pronto", 4321, 1080))
        self.assertEqual(patch_sent["thumb_path"], f"roove/{A1}.thumb.jpg")
        self.assertTrue(asset["url"].startswith("https://sb/"))
        self.assertIn(".thumb.jpg", asset["thumb_url"])

    async def test_missing_object_keeps_pending(self):
        p = self.patches(pending_row(), [None])
        with p[0], p[1], p[2], p[3], p[4], p[5] as update, p[6] as delete:
            with self.assertRaises(StudioError) as err:
                await sa.confirm_upload("roove", A1, width=None, height=None, duration_seconds=None)
        self.assertEqual(err.exception.code, "ASSET_NOT_UPLOADED")
        update.assert_not_awaited()
        delete.assert_not_awaited()

    async def test_disguised_file_is_discarded(self):
        p = self.patches(pending_row(), [{"size": 100, "mimetype": "image/png"}], head=b"<html><script>alert")
        with p[0], p[1], p[2], p[3], p[4] as remove, p[5] as update, p[6] as delete:
            with self.assertRaises(StudioError) as err:
                await sa.confirm_upload("roove", A1, width=None, height=None, duration_seconds=None)
        self.assertEqual(err.exception.code, "TYPE_MISMATCH")
        remove.assert_awaited()
        delete.assert_awaited()
        update.assert_not_awaited()

    async def test_object_bigger_than_kind_limit_is_discarded(self):
        p = self.patches(pending_row(), [{"size": 16 * MB, "mimetype": "image/png"}])
        with p[0], p[1], p[2], p[3], p[4], p[5], p[6] as delete:
            with self.assertRaises(StudioError) as err:
                await sa.confirm_upload("roove", A1, width=None, height=None, duration_seconds=None)
        self.assertEqual(err.exception.code, "FILE_TOO_LARGE")
        delete.assert_awaited()

    async def test_bad_thumbnail_is_dropped_but_asset_survives(self):
        p = self.patches(pending_row(), [{"size": 100, "mimetype": "image/png"}, {"size": 5 * MB, "mimetype": "image/jpeg"}])
        with p[0], p[1], p[2], p[3], p[4] as remove, p[5] as update, p[6]:
            await sa.confirm_upload("roove", A1, width=None, height=None, duration_seconds=None)
        self.assertIsNone(update.await_args.kwargs["patch"]["thumb_path"])
        remove.assert_awaited_with([f"roove/{A1}.thumb.jpg"])

    async def test_path_outside_company_folder_is_never_confirmed(self):
        p = self.patches(pending_row(storage_path=f"outra/{A1}.png"), [{"size": 1, "mimetype": "image/png"}])
        with p[0], p[1] as info, p[2], p[3], p[4], p[5], p[6]:
            with self.assertRaises(StudioError):
                await sa.confirm_upload("roove", A1, width=None, height=None, duration_seconds=None)
        info.assert_not_awaited()


class ItemAssetsTests(unittest.IsolatedAsyncioTestCase):
    async def test_replaces_links_in_the_given_order(self):
        select = AsyncMock(side_effect=[
            [{"id": ITEM}],                                         # pauta existe na empresa
            [{"id": A2, "kind": "video"}, {"id": A1, "kind": "imagem"}],  # mídias prontas da empresa
            [{"item_id": ITEM, "asset_id": A2, "position": 0}, {"item_id": ITEM, "asset_id": A1, "position": 1}],
            [{"id": A1, "kind": "imagem", "storage_path": "roove/a1.png"}, {"id": A2, "kind": "video", "storage_path": "roove/a2.mp4"}],
        ])
        with patch.object(sa, "sb_select", select), patch.object(sa, "sb_delete", AsyncMock()) as delete, \
             patch.object(sa, "sb_insert_many", AsyncMock()) as insert, \
             patch.object(sa, "storage_sign_urls", AsyncMock(side_effect=fake_sign)):
            assets = await sa.set_item_assets("roove", ITEM, [A2, A1])
        self.assertEqual(delete.await_args.kwargs["filters"], {"client_id": "eq.roove", "item_id": f"eq.{ITEM}"})
        rows = insert.await_args.args[1]
        self.assertEqual([(r["asset_id"], r["position"], r["client_id"]) for r in rows], [(A2, 0, "roove"), (A1, 1, "roove")])
        self.assertEqual([a["id"] for a in assets], [A2, A1])
        self.assertIsNone(assets[0]["thumb_url"])  # vídeo sem miniatura não usa o próprio vídeo como miniatura

    async def test_foreign_pending_or_pdf_assets_are_refused(self):
        cases = (
            ([{"id": A1, "kind": "imagem"}], "ASSETS_INVALID"),    # A2 é de outra empresa ou pendente
            ([{"id": A1, "kind": "imagem"}, {"id": A2, "kind": "pdf"}], "ASSET_KIND_INVALID"),
        )
        for found, code in cases:
            with self.subTest(code=code), \
                 patch.object(sa, "sb_select", AsyncMock(side_effect=[[{"id": ITEM}], found])), \
                 patch.object(sa, "sb_delete", AsyncMock()) as delete:
                with self.assertRaises(StudioError) as err:
                    await sa.set_item_assets("roove", ITEM, [A1, A2])
                self.assertEqual(err.exception.code, code)
                delete.assert_not_awaited()

    async def test_limits_duplicates_and_unknown_item(self):
        with self.assertRaises(StudioError) as err:
            await sa.set_item_assets("roove", ITEM, [A1, A1])
        self.assertEqual(err.exception.code, "ASSETS_DUPLICATED")
        with self.assertRaises(StudioError) as err:
            await sa.set_item_assets("roove", ITEM, [f"{i:08d}-0000-0000-0000-000000000000" for i in range(21)])
        self.assertEqual(err.exception.code, "TOO_MANY_ASSETS")
        with patch.object(sa, "sb_select", AsyncMock(return_value=[])):
            with self.assertRaises(StudioError) as err:
                await sa.set_item_assets("roove", ITEM, [])
        self.assertEqual(err.exception.code, "ITEM_NOT_FOUND")

    async def test_public_view_exposes_only_minimal_fields(self):
        select = AsyncMock(side_effect=[
            [{"item_id": ITEM, "asset_id": A1, "position": 0}],
            [{"id": A1, "kind": "imagem", "mime_type": "image/png", "name": "segredo-v3.png", "folder": "Interno",
              "tags": ["x"], "storage_path": "roove/a1.png", "created_by": "u1", "width": 1080, "height": 1350}],
        ])
        with patch.object(sa, "sb_select", select), patch.object(sa, "storage_sign_urls", AsyncMock(side_effect=fake_sign)):
            items = await sa.attach_assets("roove", [{"id": ITEM, "title": "t"}], public=True)
        asset = items[0]["assets"][0]
        self.assertEqual(set(asset), set(sa.PUBLIC_FIELDS) | {"url", "thumb_url"})
        self.assertNotIn("storage_path", asset)

    async def test_storage_outage_does_not_break_the_calendar(self):
        with patch.object(sa, "sb_select", AsyncMock(side_effect=[[{"item_id": ITEM, "asset_id": A1, "position": 0}],
                                                                [{"id": A1, "kind": "imagem", "storage_path": "p"}]])), \
             patch.object(sa, "storage_sign_urls", AsyncMock(side_effect=StudioError("STORAGE_ERROR"))):
            items = await sa.attach_assets("roove", [{"id": ITEM}])
        self.assertEqual(items, [{"id": ITEM, "assets": []}])


class LibraryTests(unittest.IsolatedAsyncioTestCase):
    async def test_delete_removes_storage_objects_then_row(self):
        row = pending_row(status="pronto")
        with patch.object(sa, "sb_select", AsyncMock(return_value=[row])), \
             patch.object(sa, "storage_remove", AsyncMock()) as remove, \
             patch.object(sa, "sb_delete", AsyncMock(return_value=[row])) as delete:
            await sa.delete_asset("roove", A1)
        remove.assert_awaited_with([row["storage_path"], row["thumb_path"]])
        self.assertEqual(delete.await_args.kwargs["filters"], {"client_id": "eq.roove", "id": f"eq.{A1}"})

    async def test_storage_failure_keeps_the_row(self):
        with patch.object(sa, "sb_select", AsyncMock(return_value=[pending_row(status="pronto")])), \
             patch.object(sa, "storage_remove", AsyncMock(side_effect=StudioError("STORAGE_ERROR"))), \
             patch.object(sa, "sb_delete", AsyncMock()) as delete:
            with self.assertRaises(StudioError):
                await sa.delete_asset("roove", A1)
        delete.assert_not_awaited()

    async def test_rename_folder_and_tags(self):
        row = pending_row(status="pronto")
        with patch.object(sa, "sb_update", AsyncMock(side_effect=lambda table, patch, filters: [{**row, **patch}])) as update, \
             patch.object(sa, "storage_sign_urls", AsyncMock(side_effect=fake_sign)):
            asset = await sa.update_asset("roove", A1, {"name": " Capa Natal.png ", "folder": "", "tags": ["#Natal"]})
        self.assertEqual(update.await_args.kwargs["patch"], {"name": "Capa Natal.png", "folder": None, "tags": ["natal"]})
        self.assertEqual(update.await_args.kwargs["filters"]["status"], "eq.pronto")
        self.assertEqual(asset["name"], "Capa Natal.png")
        with self.assertRaises(StudioError):
            await sa.update_asset("roove", A1, {})

    async def test_list_filters_facets_and_usage(self):
        rows = [pending_row(status="pronto", folder="Natal", tags=["natal"])]
        select = AsyncMock(side_effect=[rows, [{"folder": "Natal", "tags": ["natal"]}, {"folder": None, "tags": ["bf"]}],
                                        [{"asset_id": A1}, {"asset_id": A1}]])
        with patch.object(sa, "sb_select", select), patch.object(sa, "storage_sign_urls", AsyncMock(side_effect=fake_sign)):
            result = await sa.list_assets("roove", folder="Natal", tag="Black Friday", kind="imagem", q="capa*,(x)")
        filters = select.await_args_list[0].kwargs["filters"]
        self.assertEqual(filters["client_id"], "eq.roove")
        self.assertEqual(filters["status"], "eq.pronto")
        self.assertEqual(filters["tags"], 'cs.{"black friday"}')
        self.assertNotIn(",", filters["name"])
        self.assertEqual(result["folders"], ["Natal"])
        self.assertEqual(result["tags"], ["bf", "natal"])
        self.assertEqual(result["assets"][0]["used_in"], 2)


class CleanupTests(unittest.IsolatedAsyncioTestCase):
    async def test_removes_stale_pending_objects_and_rows(self):
        rows = [{"id": A1, "storage_path": "roove/a1.png", "thumb_path": None},
                {"id": A2, "storage_path": "roove/a2.mp4", "thumb_path": "roove/a2.thumb.jpg"}]
        with patch.object(sa, "sb_select", AsyncMock(return_value=rows)) as select, \
             patch.object(sa, "storage_remove", AsyncMock()) as remove, \
             patch.object(sa, "sb_delete", AsyncMock()) as delete:
            result = await sa.cleanup_pending()
        self.assertEqual(select.await_args.kwargs["filters"]["status"], "eq.pendente")
        self.assertEqual(sorted(p for p in remove.await_args.args[0] if p), ["roove/a1.png", "roove/a2.mp4", "roove/a2.thumb.jpg"])
        self.assertEqual(delete.await_args.kwargs["filters"], {"status": "eq.pendente", "id": f"in.({A1},{A2})"})
        self.assertEqual(result, {"ok": True, "removed": 2})

    async def test_nothing_to_clean(self):
        with patch.object(sa, "sb_select", AsyncMock(return_value=[])), patch.object(sa, "storage_remove", AsyncMock()) as remove:
            self.assertEqual(await sa.cleanup_pending(older_than_hours=0), {"ok": True, "removed": 0})
        remove.assert_not_awaited()


class StorageClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_signed_upload_token_is_parsed_from_supabase_response(self):
        class Resp:
            status_code = 200
            def json(self):
                return {"url": "/object/upload/sign/studio-assets/roove/a.png?token=abc.def"}
        client = AsyncMock()
        client.post = AsyncMock(return_value=Resp())
        client.__aenter__.return_value = client
        with patch.dict("os.environ", {"SUPABASE_URL": "https://x.supabase.co", "SUPABASE_SERVICE_ROLE_KEY": "k" * 40}), \
             patch.object(sa.httpx, "AsyncClient", return_value=client):
            result = await sa.storage_sign_upload("roove/a.png")
        self.assertEqual(result["token"], "abc.def")
        self.assertEqual(result["signed_url"], "https://x.supabase.co/storage/v1/object/upload/sign/studio-assets/roove/a.png?token=abc.def")
        self.assertEqual(client.post.await_args.kwargs["headers"]["x-upsert"], "false")

    async def test_missing_configuration_is_a_clear_error(self):
        with patch.dict("os.environ", {"SUPABASE_URL": "", "SUPABASE_SERVICE_ROLE_KEY": ""}):
            with self.assertRaises(StudioError) as err:
                await sa.storage_sign_urls(["a"])
        self.assertEqual(err.exception.code, "STORAGE_NOT_CONFIGURED")


if __name__ == "__main__":
    unittest.main()
