import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const inputPath = "/Users/zz/Desktop/电车选购全要素对比表（小白专属版）.xlsx";
const input = await FileBlob.load(inputPath);
const workbook = await SpreadsheetFile.importXlsx(input);

console.log("Workbook loaded");
console.log("Worksheet names:", workbook.worksheets.items.map((s) => s.name).join(" | "));

for (const sheet of workbook.worksheets.items) {
  console.log(`\n--- ${sheet.name} ---`);
  const inspection = await workbook.inspect({
    kind: "table",
    range: `${sheet.name}!A1:Z20`,
    include: "values,formulas",
    tableMaxRows: 20,
    tableMaxCols: 26,
  });
  console.log(inspection.ndjson);
}
