import json
import unittest

from services.ig_publish import clean_collaborators, media_for

IMG = "https://x.supabase.co/storage/v1/object/public/ig-media/a.jpg"
VID = "https://x.supabase.co/storage/v1/object/public/ig-media/a.mp4"


class CollaboratorTests(unittest.TestCase):
    def test_clean(self):
        self.assertEqual(clean_collaborators(["@M2CommunityRun", "roove.oficial", "m2communityrun", "inválido!", "a", "b", "c"]),
                         ["m2communityrun", "roove.oficial", "a"])
        self.assertEqual(clean_collaborators(None), [])

    def test_goes_on_image_reels_and_carousel_parent(self):
        for fmt, art in (("imagem", IMG), ("reels", VID), ("carrossel", f"{IMG}\n{IMG}")):
            plan, problem = media_for({"format": fmt, "art_url": art, "caption_draft": "x", "collaborators": ["@m2communityrun"]})
            self.assertIsNone(problem)
            self.assertEqual(json.loads(plan["fields"]["collaborators"]), ["m2communityrun"])
            for child in plan["children"]:
                self.assertNotIn("collaborators", child)

    def test_not_on_stories_or_when_empty(self):
        plan, _ = media_for({"format": "stories", "art_url": IMG, "collaborators": ["m2communityrun"]})
        self.assertNotIn("collaborators", plan["fields"])
        plan, _ = media_for({"format": "imagem", "art_url": IMG, "collaborators": []})
        self.assertNotIn("collaborators", plan["fields"])


if __name__ == "__main__":
    unittest.main()
