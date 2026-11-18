import { describe, expect, it } from "vitest";
import type { LibraryItem } from "../../app/library";
import type { CalendarItem } from "../../app/studio";
import { combinedCreativeAssets, PREVIEW_FORMATS } from "./MetaCreativeStudio";

const asset = (patch: Partial<LibraryItem>): LibraryItem => ({
  id: "a", kind: "arquivo", category: "foto", title: "Criativo",
  url: "https://cdn.example.com/foto.jpg", side: "mugo", ...patch,
});

describe("Estúdio de criativos Meta", () => {
  it("mostra imagens da biblioteca e posts aprovados e remove URLs duplicadas", () => {
    const library = [asset({ id: "1" }), asset({ id: "2", title: "Documento", url: "https://cdn.example.com/brief.pdf", mime_type: "application/pdf" })];
    const approved = [asset({ id: "post", kind: "post", category: "aprovado", url: "https://cdn.example.com/foto.jpg" })];
    const calendar = [{ id: "calendar", title: "Foto do calendário", art_url: "https://cdn.example.com/calendar.webp" }] as CalendarItem[];
    expect(combinedCreativeAssets(library, approved, calendar)).toEqual([
      { id: "lib:1", title: "Criativo", url: "https://cdn.example.com/foto.jpg", source: "biblioteca", calendarId: null },
      { id: "cal:calendar", title: "Foto do calendário", url: "https://cdn.example.com/calendar.webp", source: "calendario", calendarId: "calendar" },
    ]);
  });
  it("não incorpora links inseguros ou não-imagens", () => {
    const data = [asset({url:"javascript:alert(1)"}),asset({url:"http://example.com/pic.jpg"}),asset({url:"https://cdn.example.com/file.pdf",mime_type:"application/pdf"})];
    expect(combinedCreativeAssets(data,[],[])).toEqual([]);
  });
  it("possui quatro prévias de recorte, não quatro configurações de publicação", () => {
    expect(PREVIEW_FORMATS.map(x=>x.ratio)).toEqual(["1:1","4:5","9:16","1,91:1"]);
  });
});
