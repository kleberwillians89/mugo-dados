import { describe, expect, it } from "vitest";
import { artSlides, isArtVideo, isDriveFolder } from "./artLinks";

const VID = "https://x.supabase.co/storage/v1/object/public/ig-media/studio-art/latinas/nova/a.mp4";
const IMG = "https://x.supabase.co/storage/v1/object/public/ig-media/studio-art/latinas/nova/b.jpg";
const FILE = "https://drive.google.com/file/d/1AbCdEfGhIjKlMnOp/view?usp=sharing";
const FOLDER = "https://drive.google.com/drive/folders/1O-Iz6I-uK8iY_VGdGZtOGTrdRzqK7ODA";

describe("prévia da arte", () => {
  it("vídeo enviado entra na prévia junto das imagens, na ordem", () => {
    expect(isArtVideo(VID)).toBe(true);
    expect(artSlides([VID, IMG, FILE].join("\n"))).toEqual([VID, IMG, "https://drive.google.com/thumbnail?id=1AbCdEfGhIjKlMnOp&sz=w1200"]);
  });
  it("pasta do Drive é reconhecida e não vira prévia", () => {
    expect(isDriveFolder(FOLDER)).toBe(true);
    expect(isDriveFolder(FILE)).toBe(false);
    expect(artSlides(FOLDER)).toEqual([]);
  });
});

import { feedRatio } from "../components/studio/ArtCarousel";
describe("proporção no feed (regra do Instagram)", () => {
  it("fica entre 4:5 e 1,91:1", () => {
    expect(feedRatio(1080, 1350)).toBeCloseTo(0.8);
    expect(feedRatio(1080, 1080)).toBe(1);
    expect(feedRatio(1080, 1920)).toBeCloseTo(0.8);   // vertical demais vira 4:5 (corta)
    expect(feedRatio(3000, 1000)).toBeCloseTo(1.91);  // deitado demais vira 1,91:1
    expect(feedRatio(0, 0)).toBeCloseTo(0.8);
  });
});
