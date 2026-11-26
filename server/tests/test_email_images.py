import unittest
from io import BytesIO

from PIL import Image

from server.services.email_images import MAX_BYTES, normalize_image
from server.services.email_marketing import EmailError


class EmailImageTests(unittest.TestCase):
    def test_supported_formats_and_transparency(self):
        for source, expected in [("JPEG", "JPEG"), ("PNG", "PNG"), ("WEBP", "PNG")]:
            with self.subTest(source=source):
                image = Image.new("RGB" if source == "JPEG" else "RGBA", (8, 8))
                stream = BytesIO()
                image.save(stream, source)
                data, kind, _ = normalize_image(stream.getvalue())
                with Image.open(BytesIO(data)) as result:
                    self.assertEqual(result.format, expected)
                    self.assertEqual(kind, f"image/{expected.lower()}")
                    if expected == "PNG":
                        self.assertEqual(result.getpixel((0, 0))[3], 0)

    def test_rejects_invalid_and_oversize(self):
        for data, status in [(b"<svg onload='alert(1)'/>", 422), (b"a" * (MAX_BYTES + 1), 413)]:
            with self.assertRaises(EmailError) as caught:
                normalize_image(data)
            self.assertEqual(caught.exception.status, status)
