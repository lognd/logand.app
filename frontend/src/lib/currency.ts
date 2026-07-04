// Mirrors backend/src/logand_backend/domain/payments/currency.py's
// decimal_places -- the frontend needs the same per-currency precision to
// format client-computed placeholders/hints (e.g. the refund form's
// "full remaining" hint) instead of hardcoding toFixed(2), which shows a
// JPY amount as "3000.00" and truncates a BHD/KWD amount's real third
// decimal (FINDINGS.md L2). Any actual submitted amount is still
// re-quantized authoritatively server-side; this only affects display.
const ZERO_DECIMAL_CURRENCIES = new Set([
  "bif",
  "clp",
  "djf",
  "gnf",
  "jpy",
  "kmf",
  "krw",
  "mga",
  "pyg",
  "rwf",
  "ugx",
  "vnd",
  "vuv",
  "xaf",
  "xof",
  "xpf",
]);

const THREE_DECIMAL_CURRENCIES = new Set(["bhd", "jod", "kwd", "omr", "tnd"]);

export function decimalPlaces(currency: string): number {
  const code = currency.toLowerCase();
  if (ZERO_DECIMAL_CURRENCIES.has(code)) return 0;
  if (THREE_DECIMAL_CURRENCIES.has(code)) return 3;
  return 2;
}

// Formats a number to the currency's real decimal precision (replacement
// for a hardcoded `.toFixed(2)`).
export function formatMajorUnits(amount: number, currency: string): string {
  return amount.toFixed(decimalPlaces(currency));
}

// Smallest valid increment for a money <input step="...">, matching the
// currency's real precision (FINDINGS.md L1). A hardcoded step="0.01"
// rejects valid 3dp BHD/KWD input (e.g. 5.125) via native step validation,
// and lets JPY inputs step by cents instead of whole units.
export function stepFor(currency: string): string {
  return (10 ** -decimalPlaces(currency)).toString();
}
