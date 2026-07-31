import rankingsJson from "../data/rankings.json";
import unpricedJson from "../data/unpriced.json";
import methodologyJson from "../data/methodology.json";
import sourcesJson from "../data/sources.json";
import coverageJson from "../data/coverage.json";

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
  makeDisplay: string;
  modelDisplay: string;
  slug: string;
  modelSlug: string;
}

export const rankings = rankingsJson as unknown as RankedCar[];
export const unpriced = unpricedJson as unknown as Array<Record<string, any>>;
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

export const BRACKETS = [
  { id: "1", label: "Up to 50,000 DKK" },
  { id: "2", label: "50,000 to 90,000 DKK" },
  { id: "3", label: "90,000 to 150,000 DKK" },
  { id: "4", label: "150,000 to 250,000 DKK" },
  { id: "5", label: "Above 250,000 DKK" },
];

export const BAND_LABEL: Record<string, string> = {
  "1": "2020 to 2022",
  "2": "2017 to 2019",
  "3": "2014 to 2016",
  "4": "2010 to 2013",
};

export function kr(value: number | null | undefined, opts: { decimals?: number } = {}): string {
  if (value === null || value === undefined) return "-";
  const n = Math.round(value);
  return n.toLocaleString("da-DK").replace(/,/g, ".") + " kr";
}

export function krPerYear(value: number | null | undefined): string {
  if (value === null || value === undefined) return "-";
  return kr(value) + "/year";
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
