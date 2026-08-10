export function hasInstagramSnapshotData(input: {
  summaryHasData: boolean;
  coveredDays: number;
  metricValues: number[];
}): boolean {
  return input.summaryHasData || input.coveredDays > 0 || input.metricValues.some((value) => value > 0);
}
