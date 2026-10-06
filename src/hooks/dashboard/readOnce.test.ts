import { expect, test, vi } from "vitest";
import { readOnce } from "./readOnce";
test("leituras concorrentes idênticas usam uma chamada e chaves de tenant/janela permanecem separadas", async () => {
  let finish!: (value: number) => void;
  const load = vi.fn(() => new Promise<number>(resolve => { finish = resolve; }));
  const first = readOnce("tenant-a:7d", load);
  const second = readOnce("tenant-a:7d", load);
  expect(load).toHaveBeenCalledOnce();
  expect(await readOnce("tenant-b:7d", async () => 2)).toBe(2);
  expect(await readOnce("tenant-a:90d", async () => 3)).toBe(3);
  finish(1);
  expect(await Promise.all([first, second])).toEqual([1, 1]);
  expect(await readOnce("tenant-a:7d", async () => 4)).toBe(4);
});
test("erro de leitura não fica cacheado como sucesso nem bloqueia retry", async () => {
  await expect(readOnce("failed", async () => { throw new Error("fixture-error"); })).rejects.toThrow("fixture-error");
  expect(await readOnce("failed", async () => 5)).toBe(5);
});
