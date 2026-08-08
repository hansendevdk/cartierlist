// Strings for components that render on both locales. Page prose (the long
// paragraphs on the homepage, methodology page, etc.) lives directly in
// src/pages/*.astro and src/pages/da/*.astro instead of in here, since that
// prose carries inline links and interpolated pipeline facts that turn into
// an unreadable mess inside a flat key-value dict.
export type Lang = "en" | "da";

export const UI = {
  en: {
    nav: {
      brackets: "Price brackets",
      runningCosts: "Cheapest to run",
      methodology: "Methodology",
    },
    footerText: "Built from public Danish vehicle registration data and UK DVSA MOT test results. Not financial advice. See the",
    footerLinkText: "methodology page",
    footerTextEnd: "for sources, licences and known limitations.",
    switcher: {
      label: "Language",
      da: "Dansk",
      en: "English",
    },
    carRow: {
      totalCost: "total cost",
      valueScore: "value score",
      runningCost: "running cost",
      costPerYear: "cost/year",
      totalCostPerYear: "total cost/year",
      buyAround: "buy around",
      confidenceSuffix: "confidence",
      confidenceTitle: (level: string) => `Price estimate confidence: ${level}`,
      hybridTitle: "Trim name mentions hybrid or plug-in. Official fuel figures for these tend to run optimistic, see methodology.",
      dieselTitle: "Over half the registered cars behind this row are diesel.",
      hybridLabel: "hybrid",
      dieselLabel: "diesel",
      runningOnlyTitle: "Running costs only, no resale data available",
      pts: (n: number) => `${n} pts`,
    },
    ledger: {
      note: "This car is old enough that we have no later resale price to compare against, so this is running costs only: fuel, tax, repairs.",
      buyAt: (years: string) => `Buy at ${years}`,
      sellLater: (n: number | string) => `Sell ${n} years later, you get back`,
      valueLost: "Value lost",
      valueLostDep: "Value lost (depreciation)",
      fuel: "Fuel",
      ownershipTax: "Ownership tax",
      repairs: "Repairs",
      years: (n: number | string) => `, ${n} years`,
      perYearSuffix: "/year",
      totalYears: (n: number | string) => `Total, ${n} years`,
      totalPerYear: "Total, per year",
      perYear: "Per year",
      breakdownAria: (list: string) => `Cost breakdown: ${list}`,
    },
    fuelFilter: {
      filterThisList: "Filter this list",
      hideHybrids: "Hide hybrids",
      hideDiesel: "Hide diesel",
      note: 'Hybrids are found by trim name (e.g. "Plug-in Hybrid"), not a clean data field, so this can miss a few.',
      noteLink: "Why, on the methodology page.",
    },
    mileage: {
      label: "Assume how far you drive per year",
      default: "(default)",
      note: "Changes fuel cost and how much resale value erodes with distance. Ownership tax and the repair estimate stay flat per year regardless of mileage, so a high-mileage pick understates cost a little. Ranks and tiers below update to match.",
      perYearSuffix: "/year",
    },
    chart: {
      xTitle: "Purchase price (kr)",
      yTitle: "Running cost (kr/year)",
      ariaLabel: "Scatter chart of buying price against yearly running cost, with a trend line showing the median running cost at each price band",
      tooltip: (make: string, model: string, years: string, price: string, cost: string) =>
        `${make} ${model}, ${years}: buy around ${price}, ${cost}/year to run`,
      lowestMedian: (n: string) => `lowest median: ${n}/year`,
      captionStart: (minN: number) =>
        `Each dot is one car: where it sits left-to-right is what it costs to buy, where it sits up-and-down is what it costs to run every year after that (fuel, tax, repairs, no purchase price or resale in this number). The line traces the typical (median) running cost in each 30,000 kr price band, only drawn where at least ${minN} cars back it up.`,
      hiddenNote: (n: number, price: string) =>
        ` ${n} cars over ${price} aren't shown, the price axis would mostly be empty space to fit them in.`,
    },
    confidence: { low: "low", medium: "medium", high: "high" },
  },
  da: {
    nav: {
      brackets: "Prisklasser",
      runningCosts: "Billigst i drift",
      methodology: "Metode",
    },
    footerText: "Bygget på offentlige danske køretøjsregisterdata og britiske MOT-synsresultater fra DVSA. Ikke økonomisk rådgivning. Se",
    footerLinkText: "metodesiden",
    footerTextEnd: "for kilder, licenser og kendte begrænsninger.",
    switcher: {
      label: "Sprog",
      da: "Dansk",
      en: "English",
    },
    carRow: {
      totalCost: "samlet pris",
      valueScore: "værdiscore",
      runningCost: "driftspris",
      costPerYear: "pris/år",
      totalCostPerYear: "samlet pris/år",
      buyAround: "køb omkring",
      confidenceSuffix: "sikkerhed",
      confidenceTitle: (level: string) => `Sikkerhed på prisestimat: ${level}`,
      hybridTitle: "Variantnavnet nævner hybrid eller plug-in. Officielle forbrugstal for dem er typisk optimistiske, se metode.",
      dieselTitle: "Over halvdelen af de registrerede biler bag denne række er diesel.",
      hybridLabel: "hybrid",
      dieselLabel: "diesel",
      runningOnlyTitle: "Kun driftsomkostninger, ingen gensalgsdata",
      pts: (n: number) => `${n} point`,
    },
    ledger: {
      note: "Bilen er gammel nok til, at vi ikke har en senere gensalgspris at holde den op mod, så det her er kun driftsomkostninger: brændstof, afgift, reparationer.",
      buyAt: (years: string) => `Køb i ${years}`,
      sellLater: (n: number | string) => `Sælg ${n} år senere, du får igen`,
      valueLost: "Værditab",
      valueLostDep: "Værditab",
      fuel: "Brændstof",
      ownershipTax: "Grøn ejerafgift",
      repairs: "Reparationer",
      years: (n: number | string) => `, ${n} år`,
      perYearSuffix: "/år",
      totalYears: (n: number | string) => `I alt, ${n} år`,
      totalPerYear: "I alt, per år",
      perYear: "Per år",
      breakdownAria: (list: string) => `Fordeling af omkostninger: ${list}`,
    },
    fuelFilter: {
      filterThisList: "Filtrér listen",
      hideHybrids: "Skjul hybridbiler",
      hideDiesel: "Skjul diesel",
      note: 'Hybridbiler findes via variantnavnet (fx "Plug-in Hybrid"), ikke et rent datafelt, så nogle glipper.',
      noteLink: "Hvorfor, på metodesiden.",
    },
    mileage: {
      label: "Antag hvor langt du kører per år",
      default: "(standard)",
      note: "Ændrer brændstofudgiften og hvor meget gensalgsværdien falder med kilometrene. Grøn ejerafgift og reparationsestimatet er faste per år uanset kilometertal, så et højt valg undervurderer prisen en smule. Placeringer og niveauer nedenfor opdateres.",
      perYearSuffix: "/år",
    },
    chart: {
      xTitle: "Købspris (kr)",
      yTitle: "Driftspris (kr/år)",
      ariaLabel: "Punktdiagram over købspris i forhold til årlig driftspris, med en tendenslinje der viser median-driftsprisen i hvert prisinterval",
      tooltip: (make: string, model: string, years: string, price: string, cost: string) =>
        `${make} ${model}, ${years}: køb omkring ${price}, ${cost}/år i drift`,
      lowestMedian: (n: string) => `laveste median: ${n}/år`,
      captionStart: (minN: number) =>
        `Hvert punkt er en bil: placeringen fra venstre mod højre er, hvad den koster at købe, og placeringen op og ned er, hvad den koster i drift hvert år derefter (brændstof, afgift, reparationer, hverken købspris eller gensalg indgår i tallet). Linjen følger den typiske (median) driftspris i hvert prisinterval på 30.000 kr og tegnes kun, hvor mindst ${minN} biler ligger bag.`,
      hiddenNote: (n: number, price: string) =>
        ` ${n} biler over ${price} vises ikke, prisaksen ville være mest tom plads for at få dem med.`,
    },
    confidence: { low: "lav", medium: "middel", high: "høj" },
  },
} as const;
