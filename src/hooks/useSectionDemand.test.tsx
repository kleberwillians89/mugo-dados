// @vitest-environment jsdom
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, test, vi } from "vitest";
import useSectionDemand from "./useSectionDemand";
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
test("seção fora da viewport não demanda leitura; entrada e troca de scope respeitam readiness", async () => {
  let notify: IntersectionObserverCallback;
  const disconnect = vi.fn(), observe = vi.fn();
  vi.stubGlobal("IntersectionObserver", class { constructor(callback: IntersectionObserverCallback) { notify = callback; } observe = observe; disconnect = disconnect; });
  function Harness({ scope = "a", ready = true }) {
    const { observe, enabled } = useSectionDemand(scope, ready);
    return <section ref={observe}>{String(enabled)}</section>;
  }
  const node = document.createElement("div"), root = createRoot(node);
  try {
    await act(async () => root.render(<Harness />));
    expect(node.textContent).toBe("false"); expect(observe).toHaveBeenCalledOnce();
    await act(async () => notify([{ isIntersecting: false }] as IntersectionObserverEntry[], {} as IntersectionObserver));
    expect(node.textContent).toBe("false");
    await act(async () => notify([{ isIntersecting: true }] as IntersectionObserverEntry[], {} as IntersectionObserver));
    expect(node.textContent).toBe("true");
    await act(async () => root.render(<Harness scope="b" ready={false} />));
    expect(node.textContent).toBe("false");
    await act(async () => root.render(<Harness scope="b" />));
    expect(node.textContent).toBe("false");
    await act(async () => notify([{ isIntersecting: true }] as IntersectionObserverEntry[], {} as IntersectionObserver));
    expect(node.textContent).toBe("true");
  } finally { act(() => root.unmount()); vi.unstubAllGlobals(); }
});
