import asyncio

from services import business_brain as bb


def test_fill_empty_keeps_team_text():
    out = bb.fill_empty({"segment": "Perfumaria", "audience": ""}, {"segment": "Outro", "audience": "Mulheres 25-40"})
    assert out["segment"] == "Perfumaria"
    assert out["audience"] == "Mulheres 25-40"
    assert out["goals"] is None


def test_suggest_only_asks_empty_fields(monkeypatch):
    seen = {}

    async def load(cid):
        return {"context": {"segment": "Perfumaria", **{f: None for f in bb.FIELDS if f != "segment"}}}

    async def intel(cid, use_cache=True):
        return {"marca": {"tone_of_voice": "leve"}, "lacunas": []}

    async def llm(**kw):
        seen["prompt"] = kw["prompt"]
        return {"segment": "NÃO", "audience": "Quem presenteia", "goals": "", "fontes": ["legendas dos posts"]}

    async def name(cid):
        return "Ruah"

    monkeypatch.setattr(bb, "load_business_context", load)
    monkeypatch.setattr(bb, "build_content_intelligence", intel)
    monkeypatch.setattr(bb, "llm_json", llm)
    monkeypatch.setattr(bb, "_company_name", name)
    out = asyncio.run(bb.suggest_business("c1"))
    assert out["suggestion"] == {"audience": "Quem presenteia"}
    assert '"segment"' not in seen["prompt"].split("Preencha SÓ estes campos:")[1].split("\n")[0]
    assert out["sources"] == ["legendas dos posts"]


def test_suggest_skips_when_complete(monkeypatch):
    async def load(cid):
        return {"context": {f: "ok" for f in bb.FIELDS}}

    async def boom(**kw):
        raise AssertionError("não deveria chamar a IA")

    monkeypatch.setattr(bb, "load_business_context", load)
    monkeypatch.setattr(bb, "llm_json", boom)
    assert asyncio.run(bb.suggest_business("c1"))["suggestion"] == {}
