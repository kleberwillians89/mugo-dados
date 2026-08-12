export function coveredShopifyDay(
  coverageThrough: string | null | undefined,
  date: string,
  row: { revenue: number | null | undefined; orders: number | null | undefined } | null | undefined
): { revenue: number | null; orders: number | null } | null {
  if (!coverageThrough || coverageThrough < date) return null;
  return { revenue: row?.revenue ?? 0, orders: row?.orders ?? 0 };
}
