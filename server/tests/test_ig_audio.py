import json
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import ig_audio
from services.ig_reels import apply_reels_options, clean_reels_options


class MusicOptionsTests(unittest.TestCase):
    def test_musica_vai_como_audio_configuration_e_nome_do_audio_nao_vai(self):
        plan = {"type": "reels", "fields": {"media_type": "REELS", "video_url": "https://x/v.mp4"}}
        apply_reels_options(plan, {"audio_name": "Original", "music": {"audio_id": "587784541076604", "title": "Song",
                                                                       "audio_volume": 80, "video_volume": 30}})
        self.assertEqual(json.loads(plan["fields"]["audio_configuration"]),
                         {"audio_id": "587784541076604", "audio_volume": 80, "video_volume": 30})
        self.assertNotIn("audio_name", plan["fields"])

    def test_id_invalido_some_e_volume_fica_entre_1_e_100(self):
        self.assertNotIn("music", clean_reels_options({"music": {"audio_id": "abc"}}))
        music = clean_reels_options({"music": {"audio_id": "12", "audio_volume": 0, "video_volume": 500, "cover": "http://x"}})["music"]
        self.assertEqual((music["audio_volume"], music["video_volume"]), (1, 100))
        self.assertNotIn("cover", music)

    def test_sem_musica_continua_com_nome_do_audio(self):
        plan = {"type": "reels", "fields": {}}
        apply_reels_options(plan, {"audio_name": "Original"})
        self.assertEqual(plan["fields"]["audio_name"], "Original")


class SearchTests(unittest.IsolatedAsyncioTestCase):
    async def test_busca_normaliza_resposta(self):
        response = MagicMock(status_code=200, content=b"x")
        response.json.return_value = {"audio": [
            {"audio_id": "1", "title": "Hit", "display_artist": "Banda", "duration_in_ms": 30000, "audio_type": "music",
             "cover_artwork_thumbnail_uri": "https://c/1.jpg", "download_url": "https://d/1.mp3"},
            {"audio_id": "sem-numero", "title": "X"}]}
        client = MagicMock(); client.get = AsyncMock(return_value=response)
        client.__aenter__ = AsyncMock(return_value=client); client.__aexit__ = AsyncMock(return_value=False)
        creds = {"ig_user_id": "178", "token": "t"}
        with patch("services.ig_engagement.credentials", AsyncMock(return_value=creds)), \
                patch.object(ig_audio.httpx, "AsyncClient", return_value=client):
            out = await ig_audio.search_audio("roove", "hit")
        self.assertEqual(out, [{"audio_id": "1", "title": "Hit", "artist": "Banda", "duration_ms": 30000, "cover": "https://c/1.jpg",
                                "preview_url": "https://d/1.mp3", "type": "music"}])
        params = client.get.await_args.kwargs["params"]
        self.assertEqual((params["audio_type"], params["user_id"], params["search_query"]), ("music", "178", "hit"))


class StoryStickerPositionTests(unittest.TestCase):
    def test_posicao_salva_e_arredondada(self):
        options = clean_reels_options({
            "story_sticker": "poll", "story_instruction": "Enquete",
            "story_sticker_position": {"x": 24.126, "y": 72.788},
        })
        self.assertEqual(options["story_sticker_position"], {"x": 24.13, "y": 72.79})

    def test_posicao_fora_do_limite_e_recortada(self):
        options = clean_reels_options({"story_sticker": "question",
                                       "story_sticker_position": {"x": -10, "y": 110}})
        self.assertEqual(options["story_sticker_position"], {"x": 0.0, "y": 100.0})

    def test_tamanho_do_sticker_persistido_e_limitado(self):
        for size, expected in [(60, 60), (100, 100), (140, 140), (175, 140), (5, 60)]:
            with self.subTest(size=size):
                clean = clean_reels_options({"story_sticker": "poll", "story_sticker_scale": size})
                self.assertEqual(clean["story_sticker_scale"], expected)

    def test_tamanho_invalido_ignorado(self):
        for size in (float("nan"), float("inf"), True, "grande"):
            with self.subTest(size=size):
                clean = clean_reels_options({"story_sticker": "question", "story_sticker_scale": size})
                self.assertNotIn("story_sticker_scale", clean)
        self.assertNotIn("story_sticker_scale", clean_reels_options({"story_sticker_scale": 120}))

    def test_posicao_invalida_ou_sem_sticker_nao_e_persistida(self):
        invalid = clean_reels_options({"story_sticker": "poll",
                                       "story_sticker_position": {"x": "NaN", "y": 15}})
        self.assertNotIn("story_sticker_position", invalid)
        without_sticker = clean_reels_options({"story_sticker_position": {"x": 30, "y": 50}})
        self.assertNotIn("story_sticker_position", without_sticker)



class MusicRelevanceTests(unittest.TestCase):
    def test_titulo_exato_vence_resultados_genericos(self):
        songs = [
            {"audio_id": "1", "title": "Love and Life", "artist": "Somebody"},
            {"audio_id": "2", "title": "Ocean Eyes", "artist": "Billie Eilish"},
            {"audio_id": "3", "title": "Ocean", "artist": "Different Artist"},
        ]
        ranked = sorted(((score, pos, song) for pos, song in enumerate(songs)
                         if (score := ig_audio._relevance(song, "Ocean Eyes")) > 0),
                        key=lambda item: (-item[0], item[1]))
        self.assertEqual([song["audio_id"] for _, _, song in ranked], ["2"])

    def test_artista_e_acentos_sao_encontrados(self):
        song = {"title": "Música de Verão", "artist": "João"}
        self.assertGreater(ig_audio._relevance(song, "Musica de Verao"), 0)
        self.assertGreater(ig_audio._relevance(song, "Joao"), 0)
        self.assertEqual(ig_audio._relevance(song, "Taylor Swift"), 0)

    def test_busca_vazia_preserva_o_catalogo_em_alta(self):
        self.assertEqual(ig_audio._relevance({"title": "Qualquer"}, ""), 1)


class ProviderRelevanceTests(unittest.IsolatedAsyncioTestCase):
    async def test_busca_filtra_resultados_fora_do_termo(self):
        response = MagicMock(status_code=200, content=b"x")
        response.json.return_value = {"data": [
            {"id": "1", "title": "Other Song", "display_artist": "Unknown"},
            {"id": "2", "title": "Ocean Eyes", "display_artist": "Billie Eilish"},
            {"id": "3", "title": "Eyes", "display_artist": "Someone Else"},
        ]}
        client = MagicMock(); client.get = AsyncMock(return_value=response)
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        with patch("services.ig_engagement.credentials", AsyncMock(return_value={"ig_user_id": "178", "token": "t"})), \
                patch.object(ig_audio.httpx, "AsyncClient", return_value=client):
            result = await ig_audio.search_audio("client-a", "Ocean Eyes")
        self.assertEqual([song["audio_id"] for song in result], ["2"])



class MusicaForaDoReelsTest(unittest.TestCase):
    def _item(self, fmt, art="https://cdn.x/a.jpg", music=True):
        opts = {"music": {"audio_id": "587", "title": "Hit", "artist": "Banda"}} if music else {}
        return {"format": fmt, "art_url": art, "caption_draft": "oi", "reels_options": opts}

    def test_stories_com_musica_fica_para_publicar_a_mao(self):
        from services.ig_publish import media_for
        plan, manual = media_for(self._item("stories"))
        self.assertIsNone(plan)
        self.assertIn("Hit · Banda", manual)

    def test_imagem_sem_musica_continua_automatica(self):
        from services.ig_publish import media_for
        plan, manual = media_for(self._item("imagem", music=False))
        self.assertIsNone(manual)
        self.assertEqual(plan["type"], "image")

    def test_reels_com_musica_continua_automatico(self):
        from services.ig_publish import media_for
        plan, manual = media_for(self._item("reels", art="https://cdn.x/v.mp4"))
        self.assertIsNone(manual)
        self.assertIn("audio_configuration", plan["fields"])
