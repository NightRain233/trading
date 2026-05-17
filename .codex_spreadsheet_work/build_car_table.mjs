import fs from "node:fs/promises";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const inputPath = "/Users/zz/Desktop/电车选购全要素对比表（小白专属版）.xlsx";
const outputDir = "/Users/zz/Downloads/trading/outputs/car_research";
const outputPath = `${outputDir}/电车选购全要素对比表（已补充车型信息）.xlsx`;

const headers = [
  "品牌",
  "车型",
  "配置版本",
  "官方指导价",
  "购车优惠政策",
  "实际裸车价",
  "电池容量(度数)",
  "电池品牌/类型",
  "电机最大功率",
  "电机最大扭矩",
  "车辆整备质量",
  "电机布局/驱动形式",
  "热管理系统",
  "电池护板",
  "电池循环寿命",
  "电池防水等级",
  "CLTC综合续航里程",
  "快充峰值功率",
  "0-80%快充时长",
  "慢充功率/充满时长",
  "前悬挂形式",
  "后悬挂形式",
  "轮毂材质",
  "轮胎规格/品牌",
  "0-100km/h加速时间",
  "100-0km/h刹车距离",
];

const pages = [
  { brand: "MG/名爵", model: "MG4", sourceName: "新出行 名爵MG4 参数配置", url: "https://www.xchuxing.com/car/parameter?sid=794", include: (name) => name.includes("2026款") },
  { brand: "吉利", model: "星愿", sourceName: "新出行 吉利星愿 参数配置", url: "https://www.xchuxing.com/car/parameter?sid=1245", include: (name) => name.includes("2026款") },
  { brand: "比亚迪", model: "海豚", sourceName: "新出行 比亚迪海豚 参数配置", url: "https://www.xchuxing.com/car/parameter?sid=672", include: (name) => name.includes("2025款") },
  { brand: "比亚迪", model: "海鸥", sourceName: "新出行 比亚迪海鸥 参数配置", url: "https://www.xchuxing.com/car/parameter?sid=808", include: (name) => name.includes("2025款") },
  { brand: "五菱", model: "缤果PLUS", sourceName: "新出行 五菱缤果PLUS 参数配置", url: "https://www.xchuxing.com/car/parameter?sid=1109", include: (name) => name.includes("2024款") },
  { brand: "零跑", model: "Lafa5", sourceName: "新出行 零跑Lafa5 参数配置", url: "https://www.xchuxing.com/car/parameter?sid=1368", include: (name) => name.includes("2025款") },
  { brand: "领克", model: "Z20", sourceName: "新出行 领克Z20 参数配置", url: "https://www.xchuxing.com/car/parameter?sid=1322", include: (name) => name.includes("2026款") || name.includes("2025款") },
  { brand: "长安启源", model: "Q05", sourceName: "新出行 长安启源Q05 参数配置", url: "https://www.xchuxing.com/car/parameter?sid=1583", include: (name) => name.includes("2025款") },
  { brand: "长安启源", model: "A06", sourceName: "新出行 长安启源A06 参数配置", url: "https://www.xchuxing.com/car/parameter?sid=1581", include: (name) => name.includes("2025款") },
  { brand: "极狐", model: "阿尔法S5", sourceName: "新出行 极狐阿尔法S5 参数配置", url: "https://www.xchuxing.com/car/parameter?sid=1042", include: (name) => name.includes("2025款") },
  { brand: "零跑", model: "A10", sourceName: "新出行 零跑A10 参数配置", url: "https://www.xchuxing.com/car/parameter?sid=1601", include: (name) => name.includes("2026款") },
  { brand: "零跑", model: "B10", sourceName: "新出行 零跑B10 参数配置", url: "https://www.xchuxing.com/car/parameter?sid=1327", include: (name) => name.includes("2025款") },
  { brand: "比亚迪", model: "元UP", sourceName: "新出行 比亚迪元UP 参数配置", url: "https://www.xchuxing.com/car/parameter?sid=1101", include: (name) => name.includes("2025款") },
];

const sourceRows = [
  ["车型", "主要来源", "链接", "备注"],
  ["极狐 T1", "易车/MarkLines/新出行参数配置", "https://www.bitauto.com/article/1003104068219/", "T1车型数量、价格区间、续航和动力为上市/参数信息交叉整理；未核到的字段留空"],
  ["小鹏 MONA M03", "小鹏汽车官网参数配置表", "https://www.xiaopeng.com/m03/configuration.html", "官网列出2026款6个在售版本、价格、续航、快充、动力、轮胎等"],
  ["零跑B01", "太平洋汽车/易车/新浪汽车上市报道", "https://www.pcauto.com.cn/nation/4959/49591429.html", "正式上市价和续航/电池/电机来自上市报道；未核到的配置留空"],
];

function decodeHtml(text) {
  return text
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/\\u002F/g, "/");
}

function stripHtml(html) {
  const cleaned = html
    .replace(/<script[\s\S]*?<\/script>/g, " ")
    .replace(/<style[\s\S]*?<\/style>/g, " ")
    .replace(/<br\s*\/?>/g, " ")
    .replace(/<[^>]+>/g, " ");
  return cleanCell(decodeHtml(cleaned));
}

function cleanCell(value) {
  if (value == null) return "";
  let text = String(value)
    .replace(/\s+/g, " ")
    .replace(/[●○]\s*/g, "")
    .trim();
  if (text === "-" || text === "—" || text === "暂无") return "";
  return text;
}

function findDivEnd(html, start) {
  const tagRe = /<\/?div\b[^>]*>/gi;
  tagRe.lastIndex = start;
  let depth = 0;
  let match;
  while ((match = tagRe.exec(html))) {
    if (match[0].startsWith("</")) {
      depth -= 1;
      if (depth === 0) return tagRe.lastIndex;
    } else {
      depth += 1;
    }
  }
  return html.length;
}

function extractBlocks(html, className) {
  const blocks = [];
  const re = new RegExp(`<div[^>]*class=["'][^"']*${className}[^"']*["'][^>]*>`, "gi");
  let match;
  while ((match = re.exec(html))) {
    const start = match.index;
    const end = findDivEnd(html, start);
    blocks.push(html.slice(start, end));
    re.lastIndex = end;
  }
  return blocks;
}

function parseParameterPage(html) {
  const headerStart = html.indexOf('<div class="parameter-table-header"');
  const bodyStart = html.indexOf('<div class="parameter-section-container"', headerStart);
  const headerHtml = headerStart >= 0 && bodyStart > headerStart ? html.slice(headerStart, bodyStart) : html;

  const carNames = [...headerHtml.matchAll(/class=["']car-name["'][^>]*>([\s\S]*?)<\/div>/g)].map((m) => stripHtml(m[1]));
  const prices = [...headerHtml.matchAll(/class=["']price["'][^>]*>([\s\S]*?)<\/div>/g)].map((m) => stripHtml(m[1]));

  const rowBlocks = extractBlocks(html, "parameter-row");
  const paramRows = new Map();
  for (const block of rowBlocks) {
    const categoryMatch = block.match(/class=["'][^"']*param-category-cell[^"']*["'][^>]*>([\s\S]*?)<\/div>/);
    const label = categoryMatch ? stripHtml(categoryMatch[1]) : "";
    if (!label) continue;
    const specCells = extractBlocks(block, "param-spec-cell cell").map(stripHtml);
    if (specCells.length) paramRows.set(label, specCells);
  }

  return carNames.map((name, index) => {
    const specs = {};
    for (const [label, values] of paramRows) specs[label] = cleanCell(values[index]);
    specs["指导价"] ||= prices[index] || "";
    return { fullName: name, specs };
  });
}

function getSpec(specs, names) {
  for (const name of names) {
    if (specs[name]) return specs[name];
  }
  return "";
}

function formatFastCharge(value) {
  const clean = cleanCell(value);
  if (!clean) return "";
  if (/小时|h|min|分钟/.test(clean)) return clean;
  const num = Number(clean);
  if (Number.isFinite(num)) return `${Math.round(num * 60)}分钟`;
  return clean;
}

function formatSlowCharge(value) {
  const clean = cleanCell(value);
  if (!clean) return "";
  if (/小时|h|min|分钟/.test(clean)) return clean;
  const num = Number(clean);
  if (Number.isFinite(num)) return `${clean}小时`;
  return clean;
}

function stripSeriesName(fullName, model) {
  const aliases = [
    `比亚迪${model}`,
    `名爵${model}`,
    `长安启源${model}`,
    `零跑${model}`,
    `极狐${model}`,
    `极狐阿尔法S5`,
    `吉利${model}`,
    `五菱${model}`,
    `领克${model}`,
    "小鹏MONA M03",
    model,
  ];
  let value = fullName;
  for (const alias of aliases.sort((a, b) => b.length - a.length)) value = value.replace(alias, "");
  return value.trim();
}

function combine(...parts) {
  return parts.map(cleanCell).filter(Boolean).join(" / ");
}

function sourceRow(page) {
  return [page.model, page.sourceName, page.url, "新出行参数页；按当前在售/最新年款筛选"];
}

function xcxToTableRow(page, parsed) {
  const specs = parsed.specs;
  const batteryType = getSpec(specs, ["电池类型"]);
  const batteryBrand = getSpec(specs, ["电芯品牌"]);
  const drive = combine(getSpec(specs, ["电机布局"]), getSpec(specs, ["驱动方式"]));
  const thermal = combine(
    getSpec(specs, ["电池冷却方式", "电池温度管理系统"]),
    getSpec(specs, ["热泵管理系统"]) ? `热泵：${getSpec(specs, ["热泵管理系统"])}` : ""
  );
  const frontTire = getSpec(specs, ["前轮胎规格尺寸"]);
  const rearTire = getSpec(specs, ["后轮胎规格尺寸"]);
  const tire = frontTire && rearTire && frontTire !== rearTire ? `前${frontTire} / 后${rearTire}` : frontTire || rearTire;
  return [
    page.brand,
    page.model,
    stripSeriesName(parsed.fullName, page.model),
    getSpec(specs, ["指导价", "预售价"]),
    "",
    "",
    getSpec(specs, ["电池容量（kWh）"]),
    combine(batteryBrand, batteryType),
    getSpec(specs, ["系统综合输出功率（kW）", "电动机总功率(kW)"]),
    getSpec(specs, ["系统综合输出扭矩（N·m）", "电动机总扭矩(N·m)"]),
    getSpec(specs, ["整备质量（kg）"]),
    drive,
    thermal,
    "",
    "",
    "",
    getSpec(specs, ["纯电续航里程（km）"]),
    "",
    formatFastCharge(getSpec(specs, ["快充时间（h）"])),
    formatSlowCharge(getSpec(specs, ["慢充时间（h）"])),
    getSpec(specs, ["前悬挂形式"]),
    getSpec(specs, ["后悬挂形式"]),
    "",
    tire,
    getSpec(specs, ["0-100km/h加速时间（s）", "官方百公里加速时间(s)"]),
    getSpec(specs, ["100-0km/h制动距离（m）"]),
  ];
}

function xpengRows() {
  const versions = [
    ["540 长续航 Plus", "119,800", "51.8", "540", "≥26分钟（30%-80%）"],
    ["640 超长续航 Plus", "129,800", "62.2", "640", "≥26分钟（30%-80%）"],
    ["510 长续航 Max", "129,800", "51.8", "510", "≥26分钟（30%-80%）"],
    ["610 超长续航 Max", "139,800", "61.6", "610", "≥15分钟（30%-80%）"],
    ["510 长续航 Ultra SE", "141,800", "51.8", "510", "≥26分钟（30%-80%）"],
    ["610 超长续航 Ultra SE", "151,800", "61.6", "610", "≥15分钟（30%-80%）"],
  ];
  return versions.map(([version, price, battery, range, fastCharge]) => [
    "小鹏",
    "MONA M03",
    `2026款 ${version}`,
    `${price}元`,
    "",
    "",
    battery,
    "磷酸铁锂电池（IP68级防尘防水）",
    "160",
    "250",
    "",
    "前置前驱",
    "液冷恒温无热蔓延技术；XP-HP AI热管理系统（含热泵空调）",
    "",
    "",
    "IP68",
    `${range}（CLTC）`,
    "",
    fastCharge,
    "",
    "麦弗逊式独立悬架",
    "扭力梁式半独立悬架",
    "",
    "215/50 R18；可选235/40 R19 米其林",
    "7.4",
    "",
  ]);
}

function arcfoxT1Rows() {
  const common = {
    batteryBrand: "中创新航/巨湾技研/因湃电池 / 磷酸铁锂电池",
    drive: "前置前驱",
    thermal: "液冷；热泵标配",
    front: "麦弗逊式独立悬挂",
    rear: "纵臂扭转梁式非独立悬挂",
    fast: "17分钟",
  };
  const data = [
    ["2025款 320 PRO", "6.28万", "33.4", "95", "176", "1415", "320（CLTC）", "11小时", "215/55 R17"],
    ["2025款 320 PLUS", "6.58万", "33.4", "95", "176", "1415", "320（CLTC）", "11小时", "215/55 R17"],
    ["2025款 425 PRO", "6.98万", "42.3", "70", "176", "1420", "425（CLTC）", "7.5小时", "215/55 R17"],
    ["2025款 425 PLUS", "7.78万", "42.3", "70", "176", "1420", "425（CLTC）", "7.5小时", "215/55 R18"],
    ["2025款 425 MAX", "8.78万", "42.3", "70", "176", "1420", "425（CLTC）", "7.5小时", "215/55 R18"],
  ];
  return data.map(([version, price, battery, power, torque, weight, range, slow, tire]) => [
    "极狐",
    "T1",
    version,
    price,
    "",
    "",
    battery,
    common.batteryBrand,
    power,
    torque,
    weight,
    common.drive,
    common.thermal,
    "",
    "",
    "",
    range,
    "",
    common.fast,
    slow,
    common.front,
    common.rear,
    "",
    tire,
    "",
    "",
  ]);
}

function leapB01Rows() {
  const data = [
    ["430舒享版", "8.98万", "43.9", "430（CLTC）", "100"],
    ["550舒享版", "9.58万", "56.2", "550（CLTC）", "132"],
    ["550悦享版", "10.38万", "56.2", "550（CLTC）", "160"],
    ["650悦享版", "10.98万", "67.1", "650（CLTC）", "160"],
    ["550激光雷达版", "11.38万", "56.2", "550（CLTC）", "160"],
    ["650激光雷达版", "11.98万", "67.1", "650（CLTC）", "160"],
  ];
  return data.map(([version, price, battery, range, power]) => [
    "零跑",
    "B01",
    `2025款 ${version}`,
    price,
    "",
    "",
    battery,
    "",
    power,
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    range,
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
  ]);
}

async function fetchText(url) {
  const response = await fetch(url, {
    headers: {
      "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/125 Safari/537.36",
    },
  });
  if (!response.ok) throw new Error(`Fetch failed ${response.status} ${url}`);
  return response.text();
}

function dedupeRows(rows) {
  const byKey = new Map();
  for (const row of rows) {
    const key = row.slice(0, 4).join("|");
    byKey.set(key, row);
  }
  return [...byKey.values()];
}

async function buildRows() {
  const allRows = [...arcfoxT1Rows()];
  for (const page of pages) {
    const html = await fetchText(page.url);
    const parsed = parseParameterPage(html);
    const filtered = parsed.filter((item) => item.fullName && page.include(item.fullName));
    const rows = dedupeRows(filtered.map((item) => xcxToTableRow(page, item)));
    if (!rows.length) {
      console.warn(`No rows parsed for ${page.model}`);
    }
    allRows.push(...rows);
    sourceRows.push(sourceRow(page));
    console.log(`${page.model}: ${rows.length} rows`);
  }
  allRows.push(...xpengRows());
  allRows.push(...leapB01Rows());

  return dedupeRows(allRows);
}

function toMatrix(rows) {
  return rows.map((row) => row.map((value) => cleanCell(value)));
}

async function writeWorkbook(rows) {
  const input = await FileBlob.load(inputPath);
  const workbook = await SpreadsheetFile.importXlsx(input);
  const sheet = workbook.worksheets.items.find((item) => item.name === "电车选购对比表");
  if (!sheet) throw new Error("找不到工作表：电车选购对比表");

  sheet.getRange("A5:Z300").values = Array.from({ length: 296 }, () => Array(26).fill(null));
  sheet.getRange(`A5:Z${rows.length + 4}`).values = toMatrix(rows);

  const sourcesSheet = workbook.worksheets.add("信息来源");
  sourcesSheet.getRange(`A1:D${sourceRows.length}`).values = sourceRows;

  await fs.mkdir(outputDir, { recursive: true });
  const output = await SpreadsheetFile.exportXlsx(workbook);
  await output.save(outputPath);
  return { workbook, outputPath };
}

const rows = await buildRows();
console.log(`Total rows: ${rows.length}`);
const { workbook } = await writeWorkbook(rows);

const check = await workbook.inspect({
  kind: "table",
  range: `电车选购对比表!A3:Z${Math.min(rows.length + 4, 20)}`,
  include: "values,formulas",
  tableMaxRows: 20,
  tableMaxCols: 26,
});
console.log(check.ndjson);

const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 100 },
  summary: "formula error scan",
});
console.log(errors.ndjson);

await workbook.render({ sheetName: "电车选购对比表", range: "A1:Z18", scale: 1 });
await workbook.render({ sheetName: "信息来源", range: "A1:D18", scale: 1 });

console.log(`Saved: ${outputPath}`);
