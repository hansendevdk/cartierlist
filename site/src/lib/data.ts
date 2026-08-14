import rankingsJson from "../data/rankings.json";
import unpricedJson from "../data/unpriced.json";
import methodologyJson from "../data/methodology.json";
import sourcesJson from "../data/sources.json";
import coverageJson from "../data/coverage.json";
import type { Lang } from "../i18n";

export interface RankedCar {
  dmr_make: string;
  dmr_model: string;
  age_band: "1" | "2" | "3" | "4";
  band_years: string;
  approx_age_years: number;
  price_bracket_id: string;
  price_bracket_label: string;
  entry_price_dkk: number;
  entry_price_reference_km: number;
  exit_age_band: string | null;
  hold_years: number | null;
  shorter_than_6yr_horizon: boolean | null;
  horizon_available: boolean;
  resale_price_dkk: number | null;
  mileage_adjustment_factor: number | null;
  depreciation_dkk: number | null;
  depreciation_available: boolean;
  fuel_total_dkk: number | null;
  ejerafgift_total_dkk: number | null;
  repair_total_dkk: number | null;
  tco_total_dkk: number | null;
  tco_per_year: number;
  running_cost_per_year: number;
  running_cost_rank_overall: number | null;
  running_cost_tier: "S" | "A" | "B" | "C" | "D" | null;
  excluded_from_running_cost_rank: boolean;
  standardized_pass_rate: number | null;
  raw_pass_rate: number | null;
  repair_burden_index: number | null;
  median_annual_fuel_cost_dkk: number | null;
  median_annual_ejerafgift_dkk: number | null;
  engagement_score: number | null;
  reliability_unstable: boolean;
  meets_stability_floor: boolean;
  dk_vehicle_count: number;
  n_nt_tests: number;
  price_n_listings: number;
  price_pooled_at_brand: boolean;
  price_calibration_factor: number;
  price_confidence: "low" | "medium" | "high";
  excluded_from_rank: boolean;
  exclusion_reason: string | null;
  cost_rank_in_group: number | null;
  cost_tier: "S" | "A" | "B" | "C" | "D" | null;
  value_for_money_score: number | null;
  value_for_money_rank_in_group: number | null;
  value_for_money_tier: "S" | "A" | "B" | "C" | "D" | null;
  is_hybrid: boolean;
  is_diesel_dominant: boolean;
  // Set only for the Suzuki/DS rows priced by borrowing a donor model's
  // depreciation curve (see build_suzuki_ds_prices.py); null for every
  // normal, foreign-listings-priced row. Drives which confidence copy shows.
  donor_model: string | null;
  makeDisplay: string;
  modelDisplay: string;
  slug: string;
  modelSlug: string;
}

export const rankings = rankingsJson as unknown as RankedCar[];

// unpriced.json comes out of a different pipeline branch than rankings.json and
// carries only age_band, not the band_years/approx_age_years that every ranked
// row has. The car page prints both straight into its <title> and lede, so
// without this the 17 unpriced models shipped a title reading "DS Ds 3,
// undefined" and a sentence reading "First registered , about years old today".
// Both fields are pure functions of age_band, so derive them here rather than
// teaching every consumer to handle the gap.
const BAND_YEARS: Record<string, string> = {
  "1": "2020-2022",
  "2": "2017-2019",
  "3": "2014-2016",
  "4": "2010-2013",
};
const BAND_APPROX_AGE: Record<string, number> = { "1": 5, "2": 8, "3": 11, "4": 14.5 };

export const unpriced = (unpricedJson as unknown as Array<Record<string, any>>).map((car) => ({
  ...car,
  band_years: car.band_years ?? BAND_YEARS[car.age_band],
  approx_age_years: car.approx_age_years ?? BAND_APPROX_AGE[car.age_band],
}));
export const methodology = methodologyJson as unknown as Array<{ fact: string; value: string; source: string; date: string }>;
export const sources = sourcesJson as unknown as {
  registrationTax: Array<Record<string, string>>;
  ejerafgift: Array<Record<string, string>>;
  fuelPrices: Array<Record<string, string>>;
  repairConstant: Array<Record<string, string>>;
  calibrationAnchors: Array<Record<string, any>>;
};
export const coverage = coverageJson as unknown as { modelCount: number; vehicleCount: number };

export const RANK_ELIGIBLE = rankings.filter((r) => !r.excluded_from_rank);
export const RUNNING_COST_ELIGIBLE = rankings
  .filter((r) => !r.excluded_from_running_cost_rank)
  .sort((a, b) => (a.running_cost_rank_overall ?? 0) - (b.running_cost_rank_overall ?? 0));

// Price brackets and age bands are printed straight into prose on both
// locales, so they're locale-keyed functions rather than a single English
// label. BRACKET_IDS carries the stable ordering/ids; bracketLabel supplies
// the text per language. Rendering car.price_bracket_id through this table
// (rather than printing the pipeline's own car.price_bracket_label field)
// also fixes a pre-existing inconsistency: the JSON stores "50,000-90,000
// DKK" with a hyphen while this file used to say "50,000 to 90,000 DKK", so
// the same bracket read two different ways depending on the page.
export const BRACKET_IDS = ["1", "2", "3", "4", "5"] as const;

const BRACKET_LABELS: Record<Lang, Record<string, string>> = {
  en: {
    "1": "Up to 50,000 DKK",
    "2": "50,000 to 90,000 DKK",
    "3": "90,000 to 150,000 DKK",
    "4": "150,000 to 250,000 DKK",
    "5": "Above 250,000 DKK",
  },
  da: {
    "1": "Op til 50.000 kr",
    "2": "50.000 til 90.000 kr",
    "3": "90.000 til 150.000 kr",
    "4": "150.000 til 250.000 kr",
    "5": "Over 250.000 kr",
  },
};

export function bracketLabel(id: string, lang: Lang): string {
  return BRACKET_LABELS[lang][id];
}

export function bracketsForLang(lang: Lang): { id: string; label: string }[] {
  return BRACKET_IDS.map((id) => ({ id, label: bracketLabel(id, lang) }));
}

const BAND_LABELS: Record<Lang, Record<string, string>> = {
  en: { "1": "2020 to 2022", "2": "2017 to 2019", "3": "2014 to 2016", "4": "2010 to 2013" },
  da: { "1": "2020 til 2022", "2": "2017 til 2019", "3": "2014 til 2016", "4": "2010 til 2013" },
};

export function bandLabel(band: string, lang: Lang): string {
  return BAND_LABELS[lang][band];
}

// Danish says "datagrundlag" (the data behind the estimate), not "sikkerhed".
// "Lav sikkerhed" on a car reads as "low safety", i.e. the car is unsafe to
// drive, which is the opposite of what this flag means. "Datagrundlag" also
// says what is actually being measured: how many comparable listings backed
// the price. Note the adjectives are neuter (lavt/højt) to agree with it.
const CONFIDENCE_LABELS: Record<Lang, Record<"low" | "medium" | "high", string>> = {
  en: { low: "low", medium: "medium", high: "high" },
  da: { low: "lavt", medium: "middel", high: "højt" },
};

export function confidenceLabel(level: "low" | "medium" | "high", lang: Lang): string {
  return CONFIDENCE_LABELS[lang][level];
}

export function kr(value: number | null | undefined, opts: { decimals?: number } = {}): string {
  if (value === null || value === undefined) return "-";
  const n = Math.round(value);
  return n.toLocaleString("da-DK").replace(/,/g, ".") + " kr";
}

export function krPerYear(value: number | null | undefined, lang: Lang = "en"): string {
  if (value === null || value === undefined) return "-";
  return kr(value) + (lang === "da" ? "/år" : "/year");
}

// Plain integer with Danish thousands separators. The replace() is a fallback
// for Node builds without full ICU data, where da-DK silently degrades to
// en-US commas; same guard as kr() above.
export function num(value: number | null | undefined): string {
  if (value === null || value === undefined) return "-";
  return Math.round(value).toLocaleString("da-DK").replace(/,/g, ".");
}

export function pct(value: number | null | undefined): string {
  if (value === null || value === undefined) return "-";
  return (value * 100).toFixed(0) + "%";
}

export function km(value: number | null | undefined): string {
  if (value === null || value === undefined) return "-";
  return Math.round(value).toLocaleString("da-DK").replace(/,/g, ".") + " km";
}

export function carsInBracket(bracketId: string): RankedCar[] {
  return RANK_ELIGIBLE.filter((r) => r.price_bracket_id === bracketId);
}

export function bandsInBracket(bracketId: string): string[] {
  const bands = new Set(carsInBracket(bracketId).map((r) => r.age_band));
  return ["1", "2", "3", "4"].filter((b) => bands.has(b));
}

// Shared frontmatter logic, factored out so the English and Danish copies of
// each page duplicate only markup, not the sorting/filtering that decides
// what that markup shows. A bug fixed here fixes both locales at once.

export interface BracketStat {
  id: string;
  label: string;
  count: number;
  median: number | null;
}

export function getBracketStats(lang: Lang): { bracketStats: BracketStat[]; cheapestBracket: BracketStat | undefined } {
  const bracketStats = bracketsForLang(lang).map((b) => {
    const cars = carsInBracket(b.id);
    const sTier = cars.filter((c) => c.cost_tier === "S" || c.cost_tier === "A");
    const median = sTier.length
      ? sTier.map((c) => c.tco_per_year).sort((a, b2) => a - b2)[Math.floor(sTier.length / 2)]
      : null;
    return { ...b, count: cars.length, median };
  });
  const cheapestBracket = bracketStats
    .filter((b) => b.median !== null)
    .sort((a, b) => (a.median! - b.median!))[0];
  return { bracketStats, cheapestBracket };
}

export function getBracketLists(bracketId: string) {
  const cars = carsInBracket(bracketId);
  const byCost = [...cars].sort((a, b) => (a.cost_rank_in_group ?? 999) - (b.cost_rank_in_group ?? 999));
  const byValue = [...cars]
    .filter((c) => c.value_for_money_rank_in_group !== null)
    .sort((a, b) => (a.value_for_money_rank_in_group ?? 999) - (b.value_for_money_rank_in_group ?? 999));
  const bandsPresent = ["1", "2", "3", "4"].filter((b) => cars.some((c) => c.age_band === b));
  const hasRunningCostOnly = cars.some((c) => !c.depreciation_available);
  return { cars, byCost, byValue, bandsPresent, hasRunningCostOnly };
}

export interface BracketDelta {
  best: RankedCar;
  worst: RankedCar;
  gapPerYear: number;
  horizonYears: number;
  totalGap: number;
}

// The value argument: same money at purchase, different money to keep it.
// Candidates require depreciation_available: true. 129 rank-eligible rows
// are old enough that the pipeline has no later resale price for them, so
// their tco_per_year is running costs only, with no depreciation in it
// (they carry the asterisk in the lists for the same reason). Comparing one
// of those against a fully priced row would pit a partial cost against a
// full one and inflate the gap. horizonYears is a min of both cars'
// hold_years, not a constant, because hold_years varies per row (3.5, 6,
// 6.5) and multiplying a shorter-horizon row out past that overstates a
// total the pipeline never modelled.
export function getBracketDelta(bracketId: string): BracketDelta | null {
  const eligible = carsInBracket(bracketId).filter((c) => c.depreciation_available === true);
  if (eligible.length < 2) return null;
  const sorted = [...eligible].sort((a, b) => a.tco_per_year - b.tco_per_year);
  const best = sorted[0];
  const worst = sorted[sorted.length - 1];
  const gapPerYear = worst.tco_per_year - best.tco_per_year;
  const horizonYears = Math.min(best.hold_years ?? 0, worst.hold_years ?? 0);
  return { best, worst, gapPerYear, horizonYears, totalGap: Math.round(gapPerYear * horizonYears) };
}

// hold_years carries a genuine decimal (3.5, 6.5), unlike everything else
// this file formats. kr()/num() round to a whole number by design; this
// only swaps the decimal separator, so "3.5" and "6" both print correctly
// in Danish (3,5 / 6) instead of being rounded into each other.
export function yearsNum(value: number, lang: Lang): string {
  const str = String(value);
  return lang === "da" ? str.replace(".", ",") : str;
}

export function getSiblingAges(car: { modelSlug: string; slug: string }, priced: boolean) {
  return priced
    ? rankings.filter((r) => r.modelSlug === car.modelSlug && r.slug !== car.slug)
    : rankings.filter((r) => r.modelSlug === car.modelSlug);
}

export function reliabilityNote(rate: number | null, lang: Lang): string {
  if (lang === "da") {
    if (rate === null) return "for få MOT-syn til at måle pålideligt";
    if (rate >= 0.85) return "klart over gennemsnittet for sin alder";
    if (rate >= 0.75) return "tæt på gennemsnittet for sin alder";
    return "under gennemsnittet for sin alder";
  }
  if (rate === null) return "not enough MOT tests to measure reliably";
  if (rate >= 0.85) return "clearly above average for its age";
  if (rate >= 0.75) return "close to average for its age";
  return "below average for its age";
}
