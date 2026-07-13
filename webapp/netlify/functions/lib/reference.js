const fs = require("fs");
const path = require("path");

const DATA_DIR = path.join(__dirname, "..", "data");
const ONET_DIR = path.join(DATA_DIR, "onet_reference");

function loadOnetFile(socCode) {
  const p = path.join(ONET_DIR, `${socCode}.txt`);
  if (!fs.existsSync(p)) return null;
  return fs.readFileSync(p, "utf-8");
}

// Parses "Official O*NET Related Occupations:" block into [{ soc_code, title }]
function parseRelatedOccupations(onetText) {
  if (!onetText) return [];
  const marker = "Official O*NET Related Occupations:";
  const idx = onetText.indexOf(marker);
  if (idx === -1) return [];
  const section = onetText.slice(idx + marker.length);
  const lines = section.split("\n").map((l) => l.trim()).filter((l) => l.startsWith("-"));
  const out = [];
  for (const line of lines) {
    const m = line.match(/^-\s*(\d{2}-\d{4}\.\d{2})\s+(.+)$/);
    if (m) out.push({ soc_code: m[1], title: m[2] });
  }
  return out;
}

let _naicsRows = null;
function loadNaicsReference() {
  if (_naicsRows) return _naicsRows;
  const csv = fs.readFileSync(path.join(DATA_DIR, "naics_reference.csv"), "utf-8");
  const lines = csv.split("\n").filter((l) => l.trim().length > 0);
  // header: naics_code,title
  _naicsRows = lines.slice(1).map((line) => {
    const idx = line.indexOf(",");
    return { naics_code: line.slice(0, idx).trim(), title: line.slice(idx + 1).trim() };
  });
  return _naicsRows;
}

// Resolve a title for a naics_code that may be stored at a different digit
// precision than the reference table (2-6 digits are all valid at their own
// hierarchy level). Try exact match, then progressively shorter prefixes.
function resolveNaicsTitle(naicsCode) {
  const rows = loadNaicsReference();
  const byCode = new Map(rows.map((r) => [r.naics_code, r.title]));
  for (let len = naicsCode.length; len >= 2; len--) {
    const prefix = naicsCode.slice(0, len);
    if (byCode.has(prefix)) return byCode.get(prefix);
  }
  return null;
}

function loadTargetSocs() {
  return JSON.parse(fs.readFileSync(path.join(DATA_DIR, "target_socs.json"), "utf-8"));
}

module.exports = {
  loadOnetFile,
  parseRelatedOccupations,
  resolveNaicsTitle,
  loadNaicsReference,
  loadTargetSocs,
};
