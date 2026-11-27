"""Disparo em massa: importar leads de planilha (Excel ou CSV)."""
import io
import os
import sys
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("APP_ENCRYPTION_KEY", "x" * 44)

from services import relationship_contacts as rc  # noqa: E402


def xlsx(rows):
    from openpyxl import Workbook
    book = Workbook()
    for row in rows:
        book.active.append(row)
    buf = io.BytesIO()
    book.save(buf)
    return buf.getvalue()


class ParseTests(unittest.TestCase):
    def test_excel_with_number_phones_and_duplicates(self):
        raw = xlsx([["Nome completo", "Telefone celular", "E-mail"], ["Ana Lima", 11999998888, "ana@x.com"],
                    ["Ana de novo", "(11) 99999-8888", ""], ["Bruno", "123", ""], [None, None, None], ["Carla", "+55 21 98888-7777", ""]])
        out = rc.sheet_contacts(rc.read_sheet("leads.xlsx", raw))
        self.assertEqual([c["phone"] for c in out["contacts"]], ["5511999998888", "5521988887777"])
        self.assertEqual((out["invalid"], out["rows"]), (1, 4))
        self.assertEqual(out["columns"], {"telefone": "Telefone celular", "nome": "Nome completo", "email": "E-mail"})

    def test_csv_with_semicolon_and_latin1(self):
        raw = "nome;whatsapp\nJoão;11 98765-4321\n".encode("latin-1")
        out = rc.sheet_contacts(rc.read_sheet("base.csv", raw))
        self.assertEqual(out["contacts"], [{"phone": "5511987654321", "name": "João", "email": ""}])

    def test_clear_errors(self):
        for name, raw, part in (("a.xls", b"x", ".xls antigo"), ("a.pdf", b"x", ".xlsx ou .csv"),
                                ("a.csv", b"nome;email\nAna;a@x.com\n", "coluna de telefone"),
                                ("a.xlsx", b"nao e planilha", "Não consegui abrir")):
            with self.assertRaises(rc.ContactSyncError) as ctx:
                rc.sheet_contacts(rc.read_sheet(name, raw))
            self.assertIn(part, ctx.exception.message)


class ImportTests(unittest.IsolatedAsyncioTestCase):
    async def test_import_encrypts_and_can_replace(self):
        upsert, delete = AsyncMock(), AsyncMock()
        with patch.object(rc, "sb_upsert", upsert), patch("services.ig_supabase.sb_delete", delete), \
                patch.object(rc, "encrypt_secret", side_effect=lambda v: f"enc:{v}"):
            out = await rc.import_sheet("roove", filename="l.csv", raw=b"telefone,nome\n11999998888,Ana\n", replace=True)
        delete.assert_awaited_once()
        self.assertEqual(delete.await_args.kwargs["filters"], {"client_id": "eq.roove", "provider": "eq.planilha"})
        row = upsert.await_args.args[1][0]
        self.assertEqual((row["provider"], row["phone_ciphertext"], row["name_ciphertext"]), ("planilha", "enc:5511999998888", "enc:Ana"))
        self.assertEqual(out["contacts_imported"], 1)
        self.assertNotIn("marketing_whatsapp_verified", row)  # não presume consentimento verificado

    async def test_bulk_send_reads_the_sheet_origin(self):
        from services import whatsapp_campaign_send as send
        pages = AsyncMock(return_value=[{"provider": "planilha", "phone_ciphertext": "c", "name_ciphertext": "n"}])
        with patch.object(send, "_pages", pages), patch.object(send, "_plain", side_effect=lambda v: "11999998888" if v == "c" else "Ana Lima"):
            out = await send.recipients("roove", "planilha")
        self.assertEqual(out, [{"phone": "5511999998888", "name": "Ana"}])
        self.assertEqual(pages.await_args_list[0].args[2]["provider"], "eq.planilha")



H1, H2 = "a" * 64, "b" * 64


class ManualPickTests(unittest.IsolatedAsyncioTestCase):
    async def test_send_only_to_picked_contacts(self):
        from services import whatsapp_campaign_send as send
        select = AsyncMock(return_value=[{"phone_ciphertext": "c1", "name_ciphertext": "n1"}])
        pages = AsyncMock()
        with patch.object(send, "sb_select", select), patch.object(send, "_pages", pages), \
                patch.object(send, "_plain", side_effect=lambda v: "11999998888" if v == "c1" else "Kleber"):
            out = await send.recipients("roove", "planilha", [H1, "nao-hash"])
        self.assertEqual(out, [{"phone": "5511999998888", "name": "Kleber"}])
        self.assertEqual(select.await_args.kwargs["filters"]["identity_hash"], f"in.({H1})")
        pages.assert_not_awaited()  # não varre a planilha inteira

    async def test_draft_keeps_the_pick_only_for_the_sheet(self):
        from services import whatsapp_campaign_drafts as drafts
        insert = AsyncMock(return_value={"id": "d1"})
        base = {"name": "Teste BF", "template_name": "roove_bf", "provider": "planilha", "selected_contacts": [H2, H1, H1]}
        with patch.object(drafts, "audience_preview", AsyncMock(return_value={"truncated": False, "total_contacts": 900})), \
                patch.object(drafts, "sb_insert", insert):
            out = await drafts.save_draft("roove", base, approved=True)
            self.assertEqual(insert.await_args.args[1]["audience_selection"], [H1, H2])
            self.assertEqual(out["audience"]["total_contacts"], 2)
            with self.assertRaises(ValueError):
                await drafts.save_draft("roove", {**base, "provider": "all"}, approved=True)
            await drafts.save_draft("roove", {**base, "selected_contacts": None}, approved=True)
        self.assertNotIn("audience_selection", insert.await_args.args[1])  # todos = sem seleção

    async def test_list_masks_phones_and_searches(self):
        rows = [{"identity_hash": H1, "name_ciphertext": "n:Kleber", "phone_ciphertext": "p:5511999998888"},
                {"identity_hash": H2, "name_ciphertext": "n:Ana", "phone_ciphertext": "p:5521988887777"}]
        with patch.object(rc, "_paged", AsyncMock(return_value=(rows, False))), \
                patch("services.crypto.decrypt_secret", side_effect=lambda v: v.split(":", 1)[1]):
            all_ = await rc.sheet_contacts_list("roove")
            by_digits = await rc.sheet_contacts_list("roove", q="8888")
        self.assertEqual([c["name"] for c in all_["contacts"]], ["Ana", "Kleber"])
        self.assertEqual(all_["contacts"][1]["phone"], "+55 11 9••••-8888")
        self.assertNotIn("999998888", str(all_))  # número inteiro nunca sai
        self.assertEqual([c["id"] for c in by_digits["contacts"]], [H1])


if __name__ == "__main__":
    unittest.main()
