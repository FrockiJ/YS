import fs from "node:fs/promises";
import path from "node:path";

const projectRoot = path.resolve(import.meta.dirname, "..");
const cerpDir = path.join(projectRoot, "cerp");
const workbookPath = (await fs.readdir(cerpDir))
  .filter((name) => name.toLowerCase().endsWith(".xlsx"))
  .map((name) => path.join(cerpDir, name))[0];
const campingFixturePath = path.join(cerpDir, "fake_camping_products.json");
const campingOnly = process.argv.includes("--camping-only");

if (!workbookPath && !campingOnly) throw new Error("No CERP .xlsx seed workbook found.");

const FISHING_PHOTO_URL =
  "https://images.pexels.com/photos/37539053/pexels-photo-37539053.png?cs=srgb&dl=pexels-eros-sack-525095681-37539053.jpg&fm=jpg";
const LURE_PHOTO_URL =
  "https://images.pexels.com/photos/6478128/pexels-photo-6478128.jpeg?cs=srgb&dl=pexels-karola-g-6478128.jpg&fm=jpg";
const CAMPING_PHOTO_URL =
  "https://images.pexels.com/photos/1687845/pexels-photo-1687845.jpeg?auto=compress&cs=tinysrgb&w=800";

const CATEGORY_RULES = [
  { category: "釣線", supplier: "YS 線材供應", photoUrl: FISHING_PHOTO_URL, pattern: /\b(pe|braid|nylon|fluorocarbon|leader|fc)\b|\bline\b/i },
  { category: "捲線器", supplier: "YS 捲線器供應", photoUrl: FISHING_PHOTO_URL, pattern: /\b(reel|spool|2-speed)\b|\b\d{3,4}nc\b/i },
  { category: "釣竿", supplier: "YS 釣竿供應", photoUrl: FISHING_PHOTO_URL, pattern: /\b(rod|casting|spinning|blank)\b/i },
  { category: "鉤／仕掛", supplier: "YS 鉤具仕掛供應", photoUrl: LURE_PHOTO_URL, pattern: /\b(hook|sabiki|assist|rig|octopus|jigging hook)\b/i },
  { category: "路亞／假餌", supplier: "YS 路亞供應", photoUrl: LURE_PHOTO_URL, pattern: /\b(minnow|popper|jig|metal|slow|vibe|plug|squid|egi|lure|frog|bait|dart|rattle)\b/i },
  { category: "配件", supplier: "YS 釣具配件供應", photoUrl: FISHING_PHOTO_URL, pattern: /\b(bag|box|pliers|scissors|snap|swivel|glove|cap|holder|case|tool|clip|belt|scale)\b/i },
];

const CAMPING_EXPANSIONS = [
  { category: "Tent & Shelter", supplier: "TrailForge", name: "TrailForge Ridge Expedition Tent", type: "Tent", material: "40D ripstop nylon", size: "3P", color: "Pine Green", spec: "3P / storm vestibule", start: 26, count: 35 },
  { category: "Tarp & Canopy", supplier: "PinePeak", name: "PinePeak Alpine Wing Tarp", type: "Tarp", material: "210D polyester", size: "4x4m", color: "Sand", spec: "4x4m / UV coated", start: 26, count: 35 },
  { category: "Sleeping Gear", supplier: "RiverStone", name: "RiverStone Summit Down Quilt", type: "Sleeping Bag", material: "duck down", size: "Regular", color: "Slate", spec: "-2C comfort / 800g", start: 26, count: 35 },
  { category: "Sleeping Pads & Mats", supplier: "CampNest", name: "CampNest Trail Air Pad", type: "Sleeping Pad", material: "TPU nylon", size: "Regular", color: "Moss Green", spec: "R4.2 / pump sack", start: 26, count: 35 },
  { category: "Lighting", supplier: "NorthTrek", name: "NorthTrek Rechargeable Trail Light", type: "Lantern", material: "aluminum", size: "600lm", color: "Graphite", spec: "USB-C / IPX5", start: 26, count: 35 },
  { category: "Stoves & Cookware", supplier: "SummitGrid", name: "SummitGrid Titanium Cook System", type: "Cookset", material: "titanium", size: "1.2L", color: "Titanium Gray", spec: "2P / nesting set", start: 26, count: 35 },
  { category: "Camp Furniture", supplier: "FieldAura", name: "FieldAura Trail Camp Chair", type: "Chair", material: "aluminum alloy", size: "Compact", color: "Olive", spec: "120kg load / folding", start: 26, count: 35 },
  { category: "Coolers & Water Gear", supplier: "AmberTrail", name: "AmberTrail Insulated Water Carrier", type: "Water Carrier", material: "HDPE", size: "10L", color: "Ice Blue", spec: "10L / leakproof", start: 26, count: 35 },
  { category: "Storage & Packs", supplier: "MistRidge", name: "MistRidge Trail Organizer Pack", type: "Storage Bag", material: "600D polyester", size: "30L", color: "Charcoal", spec: "30L / modular pockets", start: 26, count: 35 },
  { category: "Camping Accessories", supplier: "IronCamp", name: "IronCamp All-Terrain Stake Kit", type: "Accessory", material: "anodized aluminum", size: "12 pcs", color: "Orange", spec: "12 pcs / reflective pull", start: 26, count: 35 },
  { category: "Power & Solar", supplier: "SkyHaven", name: "SkyHaven Solar Charging Kit", type: "Solar Charger", material: "monocrystalline silicon", size: "80W", color: "Black", spec: "80W / USB-C PD", start: 26, count: 35 },
  { category: "Safety & Repair", supplier: "BaseLoom", name: "BaseLoom Backcountry Repair Kit", type: "Safety Kit", material: "stainless steel", size: "Compact", color: "Red", spec: "24 pcs / waterproof case", start: 26, count: 35 },
  { category: "Hiking Poles & Navigation", supplier: "PeakPath", name: "PeakPath Carbon Trekking Pole", type: "Trekking Pole", material: "carbon fiber", size: "110-135cm", color: "Cobalt", spec: "pair / quick-lock", start: 1, count: 60 },
  { category: "Outdoor Apparel & Footwear", supplier: "AlpineLayer", name: "AlpineLayer Trail Shell Jacket", type: "Outdoor Apparel", material: "3-layer nylon", size: "M", color: "Storm Blue", spec: "waterproof / breathable", start: 1, count: 60 },
  { category: "Hydration & Trail Nutrition", supplier: "RidgeFuel", name: "RidgeFuel Hydration Flask Set", type: "Hydration Gear", material: "BPA-free TPU", size: "1L", color: "Clear", spec: "1L / insulated sleeve", start: 1, count: 60 },
];

function isBlank(value) {
  return value === null || value === undefined || String(value).trim() === "";
}

function enrichFishingProduct(name) {
  const rule = CATEGORY_RULES.find(({ pattern }) => pattern.test(String(name || "")));
  return rule || {
    category: "綜合釣具",
    supplier: "YS 綜合釣具供應",
    photoUrl: FISHING_PHOTO_URL,
  };
}

function headerIndex(headers, header) {
  return headers.findIndex((value) => String(value || "").trim().toLowerCase() === header);
}

async function enrichWorkbook() {
  const { FileBlob, SpreadsheetFile } = await import("@oai/artifact-tool");
  const source = await FileBlob.load(workbookPath);
  const workbook = await SpreadsheetFile.importXlsx(source);
  const sheet = workbook.worksheets.getItemAt(0);
  const used = sheet.getUsedRange(true);
  const values = used.values;
  const headers = values[0].map((value) => String(value || "").trim().toLowerCase());
  const nameIndex = headerIndex(headers, "name");
  if (nameIndex < 0) throw new Error("The workbook must contain a name column.");

  const requestedHeaders = ["category", "supplier", "photo_url"];
  const indexes = {};
  for (const header of requestedHeaders) {
    let index = headerIndex(headers, header);
    if (index < 0) {
      index = headers.length;
      headers.push(header);
      indexes[header] = index;
    } else {
      indexes[header] = index;
    }
  }
  for (const header of requestedHeaders) {
    if (indexes[header] === undefined) indexes[header] = headerIndex(headers, header);
  }

  const additions = [
    ["category", "supplier", "photo_url"],
    ...values.slice(1).map((row) => {
      const enrichment = enrichFishingProduct(row[nameIndex]);
      return [
        isBlank(row[indexes.category]) ? enrichment.category : row[indexes.category],
        isBlank(row[indexes.supplier]) ? enrichment.supplier : row[indexes.supplier],
        isBlank(row[indexes.photo_url]) ? enrichment.photoUrl : row[indexes.photo_url],
      ];
    }),
  ];

  const firstAddedColumn = Math.min(...Object.values(indexes));
  if (
    indexes.supplier !== indexes.category + 1 ||
    indexes.photo_url !== indexes.supplier + 1
  ) {
    throw new Error("Existing optional columns are not contiguous; seed workbook requires manual normalization.");
  }
  const startColumn = String.fromCharCode("A".charCodeAt(0) + firstAddedColumn);
  const endColumn = String.fromCharCode("A".charCodeAt(0) + firstAddedColumn + requestedHeaders.length - 1);
  sheet.getRange(`${startColumn}1:${endColumn}${values.length}`).values = additions;
  sheet.getRange(`${startColumn}1:${endColumn}1`).format = {
    fill: "#1F4E78",
    font: { bold: true, color: "#FFFFFF" },
  };
  sheet.getRange("A:A").format.columnWidth = 16;
  sheet.getRange("B:B").format.columnWidth = 42;
  sheet.getRange("C:C").format.columnWidth = 24;
  sheet.getRange("D:D").format.columnWidth = 16;
  sheet.getRange("E:E").format.columnWidth = 18;
  sheet.getRange("F:F").format.columnWidth = 24;
  sheet.getRange("G:G").format.columnWidth = 72;
  sheet.freezePanes.freezeRows(1);

  const output = await SpreadsheetFile.exportXlsx(workbook);
  await output.save(workbookPath);
  return { rowCount: values.length - 1, workbook, sheetName: sheet.name };
}

async function enrichCampingFixture() {
  const products = JSON.parse(await fs.readFile(campingFixturePath, "utf8"));
  const existingCodes = new Set(products.map((product) => String(product.code || "").toUpperCase()));
  let nextCode = 301;
  for (const expansion of CAMPING_EXPANSIONS) {
    for (let offset = 0; offset < expansion.count; offset += 1) {
      const code = `CAMP${String(nextCode).padStart(4, "0")}`;
      nextCode += 1;
      if (existingCodes.has(code)) continue;
      const sequence = expansion.start + offset;
      const product = {
        code,
        name: `${expansion.name} ${String(sequence).padStart(2, "0")}`,
        spec1: expansion.spec,
        amount: 0,
        stock: [9, 26, 43][(nextCode - 302) % 3],
        brand: expansion.supplier,
        supplier: expansion.supplier,
        category: expansion.category,
        type: expansion.type,
        material: expansion.material,
        size: expansion.size,
        color: expansion.color,
        photo_url: CAMPING_PHOTO_URL,
      };
      products.push(product);
      existingCodes.add(code);
    }
  }
  for (const product of products) {
    if (isBlank(product.category)) product.category = "露營用品";
    if (isBlank(product.supplier)) product.supplier = "YS 露營用品供應";
    if (isBlank(product.photo_url)) product.photo_url = CAMPING_PHOTO_URL;
  }
  if (products.length !== 900 || !existingCodes.has("CAMP0900")) {
    throw new Error(`Camping fixture must contain CAMP0001-CAMP0900; found ${products.length} rows.`);
  }
  await fs.writeFile(campingFixturePath, `${JSON.stringify(products, null, 2)}\n`, "utf8");
  return products.length;
}

const workbookResult = campingOnly ? null : await enrichWorkbook();
const campingRows = await enrichCampingFixture();
if (workbookResult) {
  const workbook = workbookResult.workbook;
  const preview = await workbook.render({
    sheetName: workbookResult.sheetName,
    range: "A1:G8",
    scale: 1,
    format: "png",
  });
  await fs.writeFile(path.join(cerpDir, "mock_erp_seed_preview.png"), new Uint8Array(await preview.arrayBuffer()));
}
console.log(JSON.stringify({ workbookPath, workbookRows: workbookResult?.rowCount ?? 0, campingRows }, null, 2));
