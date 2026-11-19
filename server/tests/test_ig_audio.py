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
