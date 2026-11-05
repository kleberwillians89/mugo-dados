import asyncio
import base64
import io
import unittest
import zipfile
from unittest.mock import AsyncMock, patch

from services import brand_knowledge as bk
from services.studio_calendar import StudioError


def run(coro):
    return asyncio.run(coro)


def _zip(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, content in files.items():
            z.writestr(name, content)
    return buf.getvalue()


W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
A = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
S = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'


class ExtractTests(unittest.TestCase):
    def test_docx(self):
        raw = _zip({"word/document.xml": f'<w:document {W}><w:body><w:p><w:r><w:t>Corrida M2 todo sábado às 6h na orla</w:t></w:r></w:p></w:body></w:document>'})
        self.assertIn("sábado às 6h", bk.extract_text("guia.docx", raw))

    def test_pptx_in_slide_order(self):
        raw = _zip({"ppt/slides/slide2.xml": f'<p {A}><a:t>Segundo slide com preço R$ 89 por mês</a:t></p>',
                    "ppt/slides/slide10.xml": f'<p {A}><a:t>Décimo slide com o encerramento da apresentação</a:t></p>',
                    "ppt/slides/slide1.xml": f'<p {A}><a:t>Primeiro slide: apresentação institucional da M2</a:t></p>'})
        text = bk.extract_text("deck.pptx", raw)
        self.assertLess(text.index("Primeiro"), text.index("Segundo"))
        self.assertLess(text.index("Segundo"), text.index("Décimo"))

    def test_xlsx_shared_strings(self):
        raw = _zip({"xl/sharedStrings.xml": f'<sst {S}><si><t>Plano</t></si><si><t>Mensal premium</t></si></sst>',
                    "xl/worksheets/sheet1.xml": f'<worksheet {S}><sheetData><row><c t="s"><v>0</v></c><c><v>89</v></c></row>'
                                                f'<row><c t="s"><v>1</v></c><c><v>149</v></c></row></sheetData></worksheet>'})
        text = bk.extract_text("precos.xlsx", raw)
        self.assertIn("Plano | 89", text)
        self.assertIn("Mensal premium | 149", text)

    def test_csv_and_txt(self):
        self.assertIn("treino | 6h", bk.extract_text("a.csv", "treino,6h\nlongão,domingo às 5h30 na praia".encode()))
        self.assertIn("Tom leve", bk.extract_text("a.md", "# Tom leve e motivador, sem palavrão nem gírias".encode()))

    def test_rejects(self):
        with self.assertRaises(StudioError):
            bk.extract_text("virus.exe", b"x" * 100)
        with self.assertRaises(StudioError):
            bk.extract_text("vazio.txt", b"oi")
        with self.assertRaises(StudioError):
            bk.extract_text("quebrado.docx", b"nao e zip" * 10)
        with self.assertRaises(StudioError):
            bk.decode_upload(base64.b64encode(b"x" * (bk.MAX_BYTES + 1)).decode())


class LearnTests(unittest.TestCase):
    def test_learn_merges_and_does_not_store_document_text(self):
        upsert, insert = AsyncMock(), AsyncMock(return_value={"id": "d1"})
        llm = AsyncMock(return_value={"knowledge": "Empresa: M2\n- Treino sábado 6h", "summary": "Horários de treino", "facts_added": 2})
        with patch.object(bk, "load_knowledge", AsyncMock(return_value={"knowledge": "Empresa: M2", "sources": 1, "updated_at": None})), \
             patch.object(bk, "sb_upsert", upsert), patch.object(bk, "sb_insert", insert), \
             patch("services.studio_llm.llm_json", llm):
            out = run(bk.learn("m2", file_name="horarios.pdf", kind="produto", text="TEXTO SECRETO DO DOC " * 5, user_id="u"))
        self.assertEqual(out["sources"], 2)
        saved = upsert.call_args.args[1][0]
        self.assertEqual(saved["knowledge"], "Empresa: M2\n- Treino sábado 6h")
        doc_row = insert.call_args.args[1]
        self.assertNotIn("TEXTO SECRETO", str(doc_row))
        self.assertNotIn("TEXTO SECRETO", str(saved))
        self.assertIn("Empresa: M2", llm.call_args.kwargs["prompt"])  # conhecimento atual vai junto para consolidar

    def test_knowledge_is_capped(self):
        llm = AsyncMock(return_value={"knowledge": "x" * 9000, "summary": "s", "facts_added": 1})
        upsert = AsyncMock()
        with patch.object(bk, "load_knowledge", AsyncMock(return_value={"knowledge": "", "sources": 0, "updated_at": None})), \
             patch.object(bk, "sb_upsert", upsert), patch.object(bk, "sb_insert", AsyncMock()), \
             patch("services.studio_llm.llm_json", llm):
            run(bk.learn("m2", file_name="a.txt", kind="xyz", text="conteúdo " * 10, user_id=None))
        self.assertEqual(len(upsert.call_args.args[1][0]["knowledge"]), bk.MAX_KNOWLEDGE)

    def test_prompt_knowledge_never_raises(self):
        with patch.object(bk, "load_knowledge", AsyncMock(side_effect=RuntimeError("x"))):
            self.assertEqual(run(bk.knowledge_for_prompt("m2")), "")


if __name__ == "__main__":
    unittest.main()
