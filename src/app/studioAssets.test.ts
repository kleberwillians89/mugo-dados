import { afterEach, describe, expect, it, vi } from "vitest";

const http = vi.fn();
vi.mock("./api", () => ({ http: (...args: unknown[]) => http(...args), clientClientPath: (p: string) => `/api/clients/roove${p}` }));

import { checkFile, formatBytes, mimeOf, uploadAsset } from "./studioAssets";

const MB = 1024 * 1024;

describe("validação no navegador (o backend e o bucket conferem de novo)", () => {
  it("aceita só os tipos do bucket e infere .mov sem tipo", () => {
    expect(mimeOf({ name: "a.MOV", type: "" })).toBe("video/quicktime");
    expect(mimeOf({ name: "a.jpg", type: "image/jpeg" })).toBe("image/jpeg");
    expect(mimeOf({ name: "a.gif", type: "image/gif" })).toBeNull();
    expect(mimeOf({ name: "a.heic", type: "" })).toBeNull();
  });
  it("aplica o limite por tipo", () => {
    expect(checkFile({ name: "a.png", type: "image/png", size: 15 * MB })).toEqual({ mime: "image/png", kind: "imagem" });
    expect(checkFile({ name: "a.png", type: "image/png", size: 15 * MB + 1 })).toHaveProperty("error");
    expect(checkFile({ name: "r.mp4", type: "video/mp4", size: 200 * MB })).toEqual({ mime: "video/mp4", kind: "video" });
    expect(checkFile({ name: "r.mp4", type: "video/mp4", size: 200 * MB + 1 })).toHaveProperty("error");
    expect(checkFile({ name: "g.pdf", type: "application/pdf", size: 31 * MB })).toHaveProperty("error");
    expect(checkFile({ name: "vazio.png", type: "image/png", size: 0 })).toHaveProperty("error");
  });
  it("formata tamanhos em pt-BR", () => {
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(2048)).toBe("2 KB");
    expect(formatBytes(1.5 * MB)).toBe("1,5 MB");
    expect(formatBytes(150 * MB)).toBe("150 MB");
  });
});

class FakeXhr {
  static sent: { url: string; headers: Record<string, string>; body: unknown }[] = [];
  static status = 200;
  url = ""; status = 0; headers: Record<string, string> = {};
  upload: { onprogress: ((e: { lengthComputable: boolean; loaded: number; total: number }) => void) | null } = { onprogress: null };
  onload: (() => void) | null = null; onerror: (() => void) | null = null; onabort: (() => void) | null = null;
  open(_method: string, url: string) { this.url = url; }
  setRequestHeader(k: string, v: string) { this.headers[k] = v; }
  send(body: unknown) {
    FakeXhr.sent.push({ url: this.url, headers: this.headers, body });
    this.upload.onprogress?.({ lengthComputable: true, loaded: 5, total: 10 });
    this.status = FakeXhr.status;
    queueMicrotask(() => this.onload?.());
  }
}

describe("upload em duas etapas: o arquivo vai direto ao Storage", () => {
  afterEach(() => { http.mockReset(); FakeXhr.sent = []; FakeXhr.status = 200; vi.unstubAllGlobals(); });

  it("pede a URL, envia com progresso e só então confirma", async () => {
    vi.stubGlobal("XMLHttpRequest", FakeXhr);
    http
      .mockResolvedValueOnce({ asset: { id: "a1" }, upload: { path: "roove/a1.pdf", token: "t", signed_url: "https://sb/storage/v1/object/upload/sign/studio-assets/roove/a1.pdf?token=t" }, thumb_upload: null, max_bytes: 30 * MB })
      .mockResolvedValueOnce({ asset: { id: "a1", kind: "pdf", url: "https://sb/signed" } });
    const file = new File(["%PDF-1.7"], "Guia da marca.pdf", { type: "application/pdf" });
    const progress: number[] = [];
    const asset = await uploadAsset(file, { folder: "Marca", tags: ["guia"] }, (p) => progress.push(p));

    expect(http.mock.calls[0][0]).toBe("/api/clients/roove/studio/assets/upload-url");
    expect(JSON.parse(http.mock.calls[0][1].body)).toEqual({ file_name: "Guia da marca.pdf", mime_type: "application/pdf", size_bytes: file.size, folder: "Marca", tags: ["guia"], with_thumb: false });
    expect(FakeXhr.sent).toHaveLength(1);
    expect(FakeXhr.sent[0].url).toContain("/object/upload/sign/");
    expect(FakeXhr.sent[0].headers["Content-Type"]).toBe("application/pdf");
    expect(FakeXhr.sent[0].body).toBe(file);
    expect(http.mock.calls[1][0]).toBe("/api/clients/roove/studio/assets/a1/confirm");
    expect(progress.at(-1)).toBe(1);
    expect(asset.id).toBe("a1");
  });

  it("não confirma quando o envio ao Storage falha", async () => {
    vi.stubGlobal("XMLHttpRequest", FakeXhr);
    FakeXhr.status = 400;
    http.mockResolvedValueOnce({ asset: { id: "a1" }, upload: { path: "p", token: "t", signed_url: "https://sb/x" }, thumb_upload: null, max_bytes: MB });
    await expect(uploadAsset(new File(["x"], "a.pdf", { type: "application/pdf" }), {})).rejects.toThrow(/falhou/);
    expect(http).toHaveBeenCalledTimes(1);
  });

  it("recusa tipo não aceito antes de falar com o backend", async () => {
    await expect(uploadAsset(new File(["x"], "a.gif", { type: "image/gif" }), {})).rejects.toThrow(/Tipo não aceito/);
    expect(http).not.toHaveBeenCalled();
  });
});
