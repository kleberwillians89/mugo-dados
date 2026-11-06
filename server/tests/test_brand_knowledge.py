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


def _llm(knowledge="Empresa: M2\n- Treino sábado 6h", summary="Horários de treino", facts=2):
    return AsyncMock(return_value={"knowledge": knowledge, "summary": summary, "facts_added": facts})


class Store:
    """Banco falso: guarda o que foi inserido/atualizado para os testes conferirem."""

    def __init__(self, knowledge="Empresa: M2", sources=1):
        self.knowledge = {"knowledge": knowledge, "sources": sources, "updated_at": None}
        self.docs, self.chunks, self.updates, self.upserts, self.deleted = [], [], [], [], []

    async def insert(self, table, row, returning="representation"):
        row = {**row, "id": f"d{len(self.docs) + 1}"}
        self.docs.append(row)
        return row

    async def insert_many(self, table, rows, returning="minimal"):
        self.chunks.extend(rows)
        return {"ok": True}

    async def update(self, table, *, filters, patch, returning="representation"):
        self.updates.append(patch)
        return []

    async def upsert(self, table, rows, on_conflict):
        self.upserts.append(rows[0])
        self.knowledge = {"knowledge": rows[0]["knowledge"], "sources": rows[0]["sources"], "updated_at": None}
        return {}

    async def delete(self, table, *, filters, returning="representation"):
        self.deleted.append(filters)
        return []

    async def load(self, client_id):
        return dict(self.knowledge)

    def patches(self, llm):
        return [patch.object(bk, "sb_insert", self.insert), patch.object(bk, "sb_insert_many", self.insert_many),
                patch.object(bk, "sb_update", self.update), patch.object(bk, "sb_upsert", self.upsert),
                patch.object(bk, "sb_delete", self.delete), patch.object(bk, "load_knowledge", self.load),
                patch("services.studio_llm.llm_json", llm)]


def with_patches(patches, fn):
    for p in patches:
        p.start()
    try:
        return fn()
    finally:
        for p in reversed(patches):
            p.stop()


class ChunkTests(unittest.TestCase):
    def test_split_respects_size_and_keeps_all_text(self):
        text = "\n\n".join(f"Parágrafo {i}: " + "palavra " * 60 for i in range(20))
        chunks = bk.split_chunks(text, size=500)
        self.assertTrue(all(len(c) <= 500 for c in chunks))
        joined = " ".join(chunks)
        for i in range(20):
            self.assertIn(f"Parágrafo {i}:", joined)

    def test_giant_paragraph_is_cut(self):
        chunks = bk.split_chunks("Frase curta. " * 400, size=300)
        self.assertGreater(len(chunks), 10)
        self.assertTrue(all(0 < len(c) <= 300 for c in chunks))

    def test_search_query_drops_stopwords(self):
        q = bk.search_query("Qual é o preço do plano mensal da marca?", "e o plano anual?")
        self.assertEqual(q, "preço or plano or mensal or anual")
        self.assertEqual(bk.search_query("o que é?"), "")


class LearnTests(unittest.TestCase):
    def test_text_is_saved_before_ai_and_knowledge_merged(self):
        db, llm = Store(), _llm()
        out = with_patches(db.patches(llm), lambda: run(bk.learn("m2", file_name="horarios.pdf", kind="produto",
                                                               text="TEXTO DO DOC " * 5, user_id="u")))
        self.assertEqual(db.docs[0]["status"], "pendente")          # gravado antes da IA
        self.assertIn("TEXTO DO DOC", db.chunks[0]["content"])        # conteúdo guardado
        self.assertEqual(db.chunks[0]["document_id"], "d1")
        self.assertEqual(db.updates[-1]["status"], "aprendido")
        self.assertEqual(out["sources"], 2)
        self.assertEqual(out["document"]["status"], "aprendido")
        self.assertEqual(db.upserts[0]["knowledge"], "Empresa: M2\n- Treino sábado 6h")
        self.assertIn("Empresa: M2", llm.call_args.kwargs["prompt"])  # memória atual vai junto para consolidar
        self.assertFalse(llm.call_args.kwargs["guidance"])            # sem orientação criativa: menos tokens

    def test_ai_failure_keeps_material_and_warns(self):
        db = Store()
        llm = AsyncMock(side_effect=StudioError("AI_PROVIDER_TIMEOUT"))
        out = with_patches(db.patches(llm), lambda: run(bk.learn("m2", file_name="guia.pdf", kind="institucional",
                                                               text="Guia da marca M2 com tom de voz leve. " * 3, user_id="u")))
        self.assertEqual(len(db.chunks), 1)                           # nada se perdeu
        self.assertEqual(db.updates[-1], {"status": "falhou", "error": "AI_PROVIDER_TIMEOUT"})
        self.assertEqual(out["document"]["status"], "falhou")
        self.assertIn("Material guardado", out["warning"])
        self.assertEqual(out["knowledge"], "Empresa: M2")             # memória não foi apagada

    def test_chunk_failure_undoes_the_document(self):
        db = Store()

        async def boom(*a, **k):
            raise RuntimeError("down")
        patches = db.patches(_llm()) + [patch.object(bk, "sb_insert_many", boom)]
        with self.assertRaises(StudioError) as ctx:
            with_patches(patches, lambda: run(bk.learn("m2", file_name="a.txt", kind="outro", text="conteúdo " * 10, user_id=None)))
        self.assertEqual(ctx.exception.code, "DOC_SAVE_FAILED")
        self.assertEqual(db.deleted[0]["id"], "eq.d1")

    def test_ai_reads_only_the_start_of_long_documents(self):
        db, llm = Store(), _llm()
        text = "x" * (bk.MAX_SOURCE_CHARS + 5000)
        with_patches(db.patches(llm), lambda: run(bk.learn("m2", file_name="longo.txt", kind="outro", text=text, user_id=None)))
        self.assertLess(len(llm.call_args.kwargs["prompt"]), bk.MAX_SOURCE_CHARS + 500)
        self.assertEqual(sum(len(c["content"]) for c in db.chunks), len(text))  # mas tudo fica guardado

    def test_knowledge_is_capped(self):
        db = Store(knowledge="", sources=0)
        with_patches(db.patches(_llm(knowledge="x" * 9000)),
                     lambda: run(bk.learn("m2", file_name="a.txt", kind="xyz", text="conteúdo " * 10, user_id=None)))
        self.assertEqual(len(db.upserts[0]["knowledge"]), bk.MAX_KNOWLEDGE)
        self.assertEqual(db.docs[0]["kind"], "outro")

    def test_retry_reads_saved_chunks(self):
        db, llm = Store(), _llm()
        doc = {"id": "d9", "name": "guia.pdf", "kind": "institucional", "status": "falhou"}
        patches = db.patches(llm) + [
            patch.object(bk, "sb_select", AsyncMock(side_effect=[[doc], [{"content": "Parte 1", "position": 0},
                                                                         {"content": "Parte 2", "position": 1}]]))]
        out = with_patches(patches, lambda: run(bk.retry("m2", "d9", user_id="u")))
        self.assertIn("Parte 1\n\nParte 2", llm.call_args.kwargs["prompt"])
        self.assertEqual(out["document"]["status"], "aprendido")

    def test_retry_unknown_document(self):
        with patch.object(bk, "sb_select", AsyncMock(return_value=[])):
            with self.assertRaises(StudioError) as ctx:
                run(bk.retry("m2", "nao-existe", user_id="u"))
        self.assertEqual(ctx.exception.code, "DOC_NOT_FOUND")

    def test_facts_enter_memory_without_ai(self):
        db, llm = Store(), _llm()
        out = with_patches(db.patches(llm), lambda: run(bk.add_facts("m2", ["A M2 não faz promoção em dezembro", " ", "ok"],
                                                                   user_id="u")))
        llm.assert_not_called()                                        # zero token
        self.assertIn("Aprendido nas conversas:\n- A M2 não faz promoção em dezembro", out["knowledge"])
        self.assertEqual(db.docs[0]["kind"], "conversa")
        self.assertEqual(db.docs[0]["status"], "aprendido")
        again = with_patches(db.patches(llm), lambda: run(bk.add_facts("m2", ["Corrida aos sábados às 6h"], user_id="u")))
        self.assertEqual(again["knowledge"].count("Aprendido nas conversas:"), 1)

    def test_facts_use_ai_when_memory_is_full(self):
        db, llm = Store(knowledge="y" * bk.MAX_KNOWLEDGE), _llm()
        with_patches(db.patches(llm), lambda: run(bk.add_facts("m2", ["Fato novo e importante da marca"], user_id="u")))
        llm.assert_called_once()

    def test_empty_facts(self):
        with self.assertRaises(StudioError):
            run(bk.add_facts("m2", ["", "  "], user_id="u"))

    def test_prompt_knowledge_never_raises(self):
        with patch.object(bk, "load_knowledge", AsyncMock(side_effect=RuntimeError("x"))):
            self.assertEqual(run(bk.knowledge_for_prompt("m2")), "")

    def test_search_never_raises(self):
        with patch.object(bk, "sb_rpc", AsyncMock(side_effect=RuntimeError("sem migração"))):
            self.assertEqual(run(bk.search_chunks("m2", "preço do plano")), [])


if __name__ == "__main__":
    unittest.main()
