// Shared row-visibility logic for FuelFilterToggle and SegmentFilterToggle.
// Both act on the same .car-row elements (data-* attributes baked in at
// build time) and both can be present on the same page (the bracket pages),
// so visibility has to be computed from every active filter at once --
// each toggle setting row.style.display from only its own criterion would
// clobber whatever the other toggle had just hidden.
//
// Each filter's storage key is only consulted when that filter's own
// controls are actually present on the page. Without that guard, a segment
// preference set on a bracket page would silently keep hiding rows on
// running-costs.astro (which shares localStorage but has no segment filter
// UI to explain or undo it).
export function applyRowVisibility() {
  const hasFuelFilter = document.getElementById("hide-hybrid-toggle") !== null;
  const hasSegmentFilter = document.querySelector(".segment-toggle") !== null;

  const hideHybrid = hasFuelFilter && localStorage.getItem("hideHybrid") === "1";
  const hideDiesel = hasFuelFilter && localStorage.getItem("hideDiesel") === "1";
  const hiddenSegments = hasSegmentFilter
    ? new Set((localStorage.getItem("hiddenSegments") ?? "").split(",").filter(Boolean))
    : new Set<string>();

  document.querySelectorAll<HTMLElement>(".car-row").forEach((row) => {
    const isHybrid = row.dataset.hybrid === "1";
    const isDiesel = row.dataset.diesel === "1";
    const segment = row.dataset.segment ?? "";
    const hideForFuel = (hideHybrid && isHybrid) || (hideDiesel && isDiesel);
    const hideForSegment = hiddenSegments.has(segment);
    row.style.display = hideForFuel || hideForSegment ? "none" : "";
  });
}
