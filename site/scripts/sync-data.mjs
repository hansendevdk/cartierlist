// Pulls the finished pipeline output into src/data as JSON, typed and
// numeric-coerced, so pages never touch a CSV or the pipeline folder
// directly. Rerun after any pipeline change: npm run sync-data (also runs
// automatically before dev/build). The site never fetches or computes a
// ranking itself -- every number here was decided by the pipeline.
import { parse } from "csv-parse/sync";
import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REFERENCE = path.resolve(__dirname, "../../pipeline/reference");
const OUT_DIR = path.resolve(__dirname, "../src/data");

// Known display spellings. The pipeline works in DMR's raw all-caps make
// names; a reader should see "Skoda" and "Citroen", not "SKODA".
const MAKE_DISPLAY = {
  "ALFA ROMEO": "Alfa Romeo", AUDI: "Audi", BMW: "BMW", CHEVROLET: "Chevrolet",
  "CITROËN": "Citroen", DACIA: "Dacia", DS: "DS", FIAT: "Fiat", FORD: "Ford",
  HONDA: "Honda", HYUNDAI: "Hyundai", KIA: "Kia", MAZDA: "Mazda",
  "MERCEDES-BENZ": "Mercedes-Benz", MINI: "MINI", MITSUBISHI: "Mitsubishi",
  NISSAN: "Nissan", OPEL: "Opel", PEUGEOT: "Peugeot", RENAULT: "Renault",
  SEAT: "SEAT", SKODA: "Skoda", SUZUKI: "Suzuki", TOYOTA: "Toyota",
  VOLKSWAGEN: "Volkswagen", VOLVO: "Volvo",
};

function titleCaseModel(raw) {
  return raw
    .split(" ")
    .map((word) => {
      if (word.length === 0) return word;
      // Keep short alphanumeric codes (A3, 3-Serie, 208) as-is rather than
      // lowercasing digits-and-letters mixes; only reshape pure-letter words.
      if (/^[A-Za-z]+$/.test(word)) {
        return word[0].toUpperCase() + word.slice(1).toLowerCase();
      }
      return word;
    })
    .join(" ");
}

// donor_model comes out of the pipeline as a single raw "MAKE MODEL" string
// (e.g. "TOYOTA YARIS"); every current donor has a one-word make, so the
// first token is safe to split off. Reuses the same display helpers as the
// donor's own page, so a mention here reads exactly like that model does
// anywhere else on the site.
function formatDonor(raw) {
  if (!raw) return null;
  const [make, ...modelParts] = raw.split(" ");
  return `${MAKE_DISPLAY[make] ?? make} ${titleCaseModel(modelParts.join(" "))}`;
}

function slugify(make, model) {
  return `${make}-${model}`
    .toLowerCase()
    .normalize("NFD").replace(/[̀-ͯ]/g, "") // strip diacritics
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

function readCsv(filename) {
  const p = path.join(REFERENCE, filename);
  if (!existsSync(p)) throw new Error(`Missing pipeline output: ${p}. Run the pipeline first.`);
  return parse(readFileSync(p, "utf-8"), { columns: true, skip_empty_lines: true });
}

// Columns that must stay strings even when their value looks numeric --
// model/make/band identifiers ("208", "3", "500") are names, not numbers.
const ALWAYS_STRING = new Set([
  "dmr_make", "dmr_model", "age_band", "exit_age_band", "price_bracket_id",
  "band_years", "segment",
]);

const TRUE_STRINGS = new Set(["True", "true"]);
function coerce(value) {
  if (value === "") return null;
  if (TRUE_STRINGS.has(value)) return true;
  if (value === "False" || value === "false") return false;
  if (value !== "" && !Number.isNaN(Number(value)) && /^-?[0-9.]+$/.test(value)) return Number(value);
  return value;
}
function coerceRow(row) {
  const out = {};
  for (const [k, v] of Object.entries(row)) out[k] = ALWAYS_STRING.has(k) ? v : coerce(v);
  return out;
}

// --- bracket rankings: the core dataset every ranked page reads --------
const rankingsRaw = readCsv("model_bracket_rankings.csv").map(coerceRow);
const rankings = rankingsRaw.map((r) => ({
  ...r,
  makeDisplay: MAKE_DISPLAY[r.dmr_make] ?? r.dmr_make,
  modelDisplay: titleCaseModel(r.dmr_model),
  slug: slugify(r.dmr_make, r.dmr_model) + "--band" + r.age_band,
  modelSlug: slugify(r.dmr_make, r.dmr_model),
  donor_model: formatDonor(r.donor_model),
}));
writeFileSync(path.join(OUT_DIR, "rankings.json"), JSON.stringify(rankings));

// --- unpriced models (Suzuki/DS): shown without a value rank -----------
const metricsRaw = readCsv("model_age_band_metrics.csv").map(coerceRow);
const rankedKeys = new Set(rankings.map((r) => `${r.dmr_make}|${r.dmr_model}|${r.age_band}`));
const unpriced = metricsRaw
  .filter((r) => !rankedKeys.has(`${r.dmr_make}|${r.dmr_model}|${r.age_band}`))
  .map((r) => ({
    ...r,
    makeDisplay: MAKE_DISPLAY[r.dmr_make] ?? r.dmr_make,
    modelDisplay: titleCaseModel(r.dmr_model),
    slug: slugify(r.dmr_make, r.dmr_model) + "--band" + r.age_band,
    modelSlug: slugify(r.dmr_make, r.dmr_model),
  }));
writeFileSync(path.join(OUT_DIR, "unpriced.json"), JSON.stringify(unpriced));

// --- methodology facts ---------------------------------------------------
const methodology = readCsv("methodology_counts.csv");
writeFileSync(path.join(OUT_DIR, "methodology.json"), JSON.stringify(methodology));

// --- reference tables the methodology page cites verbatim ---------------
const registrationTax = readCsv("registration_tax_2026.csv");
const ejerafgift = readCsv("ejerafgift_rates.csv");
const fuelPrices = readCsv("fuel_prices.csv");
const repairConstant = readCsv("repair_cost_constant.csv");
const calibrationAnchors = readCsv("calibration_prices.csv").map(coerceRow);
writeFileSync(path.join(OUT_DIR, "sources.json"), JSON.stringify({
  registrationTax, ejerafgift, fuelPrices, repairConstant, calibrationAnchors,
}));

// --- crosswalk: fleet coverage figure for the homepage narrative --------
const crosswalk = readCsv("crosswalk.csv").map(coerceRow);
const totalCovered = crosswalk.reduce((sum, r) => sum + (r.dk_vehicle_count ?? 0), 0);
writeFileSync(path.join(OUT_DIR, "coverage.json"), JSON.stringify({
  modelCount: crosswalk.length,
  vehicleCount: totalCovered,
}));

console.log(`synced: ${rankings.length} ranked rows, ${unpriced.length} unpriced rows, ` +
  `${methodology.length} methodology facts, ${crosswalk.length} crosswalk models`);
