import { expect, test, vi } from "vitest";
import { markReadStage, type ReadStage } from "./readPerformance";
test("marcos cobrem auth até secundários com somente fase e tempo", () => {
  const log = vi.spyOn(console, "info").mockImplementation(() => {});
  const stages: ReadStage[] = ["auth_start", "auth_ready", "tenant_start", "tenant_ready", "snapshot_request_start", "snapshot_ready", "first_useful_data", "secondary_data_ready"];
  stages.forEach(markReadStage);
  expect(log.mock.calls.map(call => call[1].stage)).toEqual(stages);
  for (const call of log.mock.calls) expect(Object.keys(call[1]).sort()).toEqual(["elapsed_ms", "stage"]);
  log.mockRestore();
});
