/** Mesma regra do servidor: sem @, minúsculo, letras/números/ponto/sublinhado, até 30. */
export function cleanHandle(value: string): string | null {
  const user = value.trim().replace(/^@+/, "").toLowerCase().replace(/^https?:\/\/(www\.)?instagram\.com\//, "").replace(/\/.*$/, "");
  return /^[a-z0-9._]{1,30}$/.test(user) ? user : null;
}
