import { describe, expect, it } from "vitest";
import {
  REFRESH_COOLDOWN_MS,
  cooldownFrom,
  cooldownHint,
  formatFreshness,
  hasFresherData,
} from "./dataRefresh";

const NOW = Date.parse("2026-10-04T12:00:00Z");
const minutesAgo = (minutes: number) => new Date(NOW - minutes * 60_000).toISOString();

describe("frescor dos dados", () => {
  it("diz 'agora mesmo' para a leitura recém-chegada", () => {
    expect(formatFreshness(minutesAgo(0), NOW)).toBe("agora mesmo");
  });

  it("usa minutos, horas e dias conforme a distância", () => {
    expect(formatFreshness(minutesAgo(1), NOW)).toBe("há 1 min");
    expect(formatFreshness(minutesAgo(12), NOW)).toBe("há 12 min");
    expect(formatFreshness(minutesAgo(60), NOW)).toBe("há 1 h");
    expect(formatFreshness(minutesAgo(5 * 60), NOW)).toBe("há 5 h");
    expect(formatFreshness(minutesAgo(24 * 60), NOW)).toBe("há 1 dia");
    expect(formatFreshness(minutesAgo(3 * 24 * 60), NOW)).toBe("há 3 dias");
  });

  it("sem timestamp não inventa rótulo", () => {
    for (const value of [null, undefined, "", "   ", "não-é-data"]) {
      expect(formatFreshness(value, NOW)).toBeNull();
    }
  });

  it("timestamp no futuro não vira número negativo", () => {
    expect(formatFreshness(new Date(NOW + 60_000).toISOString(), NOW)).toBe("agora mesmo");
  });
});

describe("cooldown do botão Atualizar dados", () => {
  it("libera quando nunca houve tentativa", () => {
    expect(cooldownFrom(null, NOW)).toEqual({ ready: true, secondsLeft: 0 });
  });

  it("bloqueia logo após uma tentativa", () => {
    const cooldown = cooldownFrom(NOW, NOW);
    expect(cooldown.ready).toBe(false);
    expect(cooldown.secondsLeft).toBe(REFRESH_COOLDOWN_MS / 1000);
  });

  it("conta o tempo restante enquanto o cooldown corre", () => {
    expect(cooldownFrom(NOW - 10_000, NOW).secondsLeft).toBe(20);
    expect(cooldownFrom(NOW - 29_000, NOW).secondsLeft).toBe(1);
  });

  it("libera quando a janela termina", () => {
    expect(cooldownFrom(NOW - REFRESH_COOLDOWN_MS, NOW).ready).toBe(true);
    expect(cooldownFrom(NOW - REFRESH_COOLDOWN_MS - 1, NOW).ready).toBe(true);
  });

  it("explica discretamente só quando está bloqueado", () => {
    expect(cooldownHint(cooldownFrom(null, NOW))).toBeNull();
    expect(cooldownHint(cooldownFrom(NOW - 10_000, NOW))).toBe("Aguarde 20s para atualizar de novo.");
  });
});

describe("dados mais recentes que a análise", () => {
  it("avisa quando a sincronização é claramente posterior", () => {
    expect(hasFresherData(minutesAgo(1), minutesAgo(90))).toBe(true);
  });

  it("não avisa quando a análise é a mais nova", () => {
    expect(hasFresherData(minutesAgo(90), minutesAgo(1))).toBe(false);
  });

  it("tolera a diferença de relógio entre job e banco", () => {
    // Trinta segundos não é "dado mais novo", é ruído de relógio.
    expect(hasFresherData(minutesAgo(0), minutesAgo(0.5))).toBe(false);
  });

  it("sem um dos timestamps não afirma nada", () => {
    expect(hasFresherData(null, minutesAgo(10))).toBe(false);
    expect(hasFresherData(minutesAgo(10), null)).toBe(false);
    expect(hasFresherData(undefined, undefined)).toBe(false);
  });
});
