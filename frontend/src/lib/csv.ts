// Single CSV export helper used across pages.
// `columns` is an array of strings (the header row).
// `rows` is an array of arrays (one per data row), values stringified verbatim.
// `filenameBase` becomes `${filenameBase}-YYYY-MM-DD.csv`.

// Cells are any value that meaningfully has a string representation. null /
// undefined are explicitly allowed (rendered as ""); numbers, booleans, dates,
// etc. go through String() coercion in `escape()`.
export type CSVCell = string | number | boolean | null | undefined;

function escape(v: CSVCell): string {
  return `"${String(v ?? "").replace(/"/g, '""')}"`;
}

export function exportCSV(
  columns: readonly string[],
  rows: readonly (readonly CSVCell[])[],
  filenameBase: string,
): void {
  const today = new Date().toISOString().slice(0, 10);
  const csv = [
    columns.join(","),
    ...rows.map((r) => r.map(escape).join(",")),
  ].join("\n");
  const blob = new Blob([csv], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${filenameBase}-${today}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}
