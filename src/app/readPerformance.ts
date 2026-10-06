/** Marcos operacionais do navegador: nenhum identificador, payload ou credencial. */
export type ReadStage = "auth_start" | "auth_ready" | "tenant_start" | "tenant_ready" | "snapshot_request_start" | "snapshot_ready" | "first_useful_data" | "secondary_data_ready";
let started = performance.now();
export function markReadStage(stage: ReadStage) {
  if (stage === "auth_start") started = performance.now();
  const at = performance.now();
  performance.mark(`mugo:${stage}`);
  console.info("[performance][read_stage]", { stage, elapsed_ms: Math.round(at - started) });
}
