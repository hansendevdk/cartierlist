# Phase 1 -> Phase 2 crosswalk prep

In-scope Danish fleet (Personbil, Registreret, 2010-2022, deduped by chassis): **1,778,307 vehicles** across **29,042 variant rows**.

Distinct models grouped by (make_id, model_id): **5,188**

Distinct models grouped by (make_name, model_name) string: **5,112**

Difference: **76** -- this many model_id groupings collapse into fewer distinct name strings, or vice versa (spelling variants of the same model_id, or the same name string covering multiple model_ids).

Top 150 by (make_id, model_id) covers 1,484,195 / 1,778,307 vehicles (83.5% of in-scope fleet).

## VW -> VOLKSWAGEN make fold (coverage_audit.md finding 5)

4,632 vehicles across 68 model spellings folded from DMR make string "VW" into "VOLKSWAGEN".

Merged into an existing crosswalk.csv VOLKSWAGEN row (2,874 vehicles, 10 model spellings):

| model_name | vehicle_count |
|---|---|
| PASSAT | 1,082 |
| GOLF | 764 |
| TIGUAN | 311 |
| TOURAN | 275 |
| POLO | 233 |
| PASSAT VARIANT | 140 |
| UP! | 34 |
| CADDY | 28 |
| CALIFORNIA | 5 |
| GOLF VARIANT | 2 |

Not covered by any existing crosswalk.csv VOLKSWAGEN row, not auto-added per the task's scope limit (crosswalk_review.csv is not being regenerated): 1,758 vehicles, 58 model spellings.

| model_name | vehicle_count |
|---|---|
| Passat GTE | 526 |
| GOLF GTE Hybrid | 210 |
| BEETLE | 168 |
| GOLF GTE | 146 |
| UP | 91 |
| UP 1,0 | 65 |
| Touareg | 64 |
| SHARAN | 58 |
| MULTIVAN | 48 |
| Golf 7 Variant | 46 |
| T-ROC | 33 |
| GOLF SPORTSVAN | 30 |
| GOLF 7 | 24 |
| Arteon | 23 |
| T-CROSS | 23 |
| CARAVELLE | 19 |
| Golf E-Hybrid | 17 |
| TRANSPORTER | 13 |
| TOUREG | 13 |
| GTE | 12 |
| CADDY 1,6 TDI | 9 |
| scirocco | 9 |
| Kombi | 8 |
| GOLF R | 8 |
| EOS | 8 |
| Golf Gti | 7 |
| PASSAT LIMOUSINE | 7 |
| CRAFTER | 7 |
| Touran 1T | 7 |
| Tiguan 1.4 e-HYBRID 245 HK SUV DSG6 | 5 |
| 1,4 | 5 |
| Golf ALLTRACK | 5 |
| AMAROK | 5 |
| 2,0 tdi | 4 |
| CALIFORNIA BEACH | 3 |
| SPORTSVAN | 3 |
| GOLF PLUS | 3 |
| Jetta | 2 |
| T5 | 2 |
| Caddy Maxi | 2 |
| POLO CROSS | 2 |
| 1,4 Tsi | 2 |
| Westfalia | 1 |
| T-ROC 1,0 T 115 HK | 1 |
| t2 | 1 |
| CITIGO | 1 |
| PASSAT ALLTRACK | 1 |
| CADDY 1,2 TSI | 1 |
| Touran 1,9 TDI Bluemotion | 1 |
| 1.4 TSI | 1 |
| Amorok | 1 |
| 2,0fsi | 1 |
| Wohnmobil | 1 |
| CC | 1 |
| GOLF3 | 1 |
| 1,0 | 1 |
| e-Golf | 1 |
| 1,6 TDI | 1 |

## Top 50 models by model_id grouping

| make | model | vehicle_count |
|---|---|---|
| VOLKSWAGEN | UP! | 62,570 |
| PEUGEOT | 208 | 52,719 |
| VOLKSWAGEN | POLO | 44,100 |
| TOYOTA | AYGO | 43,773 |
| TOYOTA | YARIS | 39,750 |
| CITROËN | C3 | 38,244 |
| KIA | PICANTO | 32,895 |
| CITROËN | C1 | 31,991 |
| FORD | FIESTA | 31,965 |
| VOLKSWAGEN | GOLF | 29,976 |
| HYUNDAI | I10 | 29,175 |
| SKODA | CITIGO | 27,868 |
| OPEL | CORSA | 27,644 |
| RENAULT | Ny Clio | 26,976 |
| HYUNDAI | I20 | 25,514 |
| SKODA | FABIA | 25,197 |
| SKODA | OCTAVIA | 24,510 |
| NISSAN | QASHQAI | 23,722 |
| SUZUKI | SWIFT | 22,549 |
| KIA | RIO | 21,547 |
| PEUGEOT | 308 | 20,846 |
| RENAULT | Captur | 18,881 |
| VOLKSWAGEN | TOURAN | 17,682 |
| PEUGEOT | 107 | 17,674 |
| FORD | KUGA | 16,767 |
| PEUGEOT | 2008 | 16,677 |
| PEUGEOT | 108 | 15,588 |
| VOLKSWAGEN | PASSAT | 15,030 |
| KIA | CEED | 14,992 |
| OPEL | ASTRA | 14,759 |
| FORD | FOCUS | 14,472 |
| CHEVROLET | SPARK | 12,832 |
| FORD | KA | 12,679 |
| MERCEDES-BENZ | C-Klasse | 12,063 |
| SEAT | MII | 11,905 |
| PEUGEOT | 3008 | 11,806 |
| FIAT | 500 | 11,378 |
| TOYOTA | AURIS | 10,970 |
| SUZUKI | VITARA | 9,524 |
| RENAULT | MEGANE | 9,277 |
| SEAT | LEON | 9,206 |
| HYUNDAI | I30 | 9,003 |
| SUZUKI | SX4 S-Cross | 8,987 |
| OPEL | KARL | 8,920 |
| SUZUKI | BALENO | 8,873 |
| VOLKSWAGEN | T-Roc | 8,548 |
| SKODA | OCTAVIA COMBI | 8,432 |
| SUZUKI | Celerio | 8,391 |
| RENAULT | CLIO | 8,289 |
| CITROËN | C4 | 8,280 |

## Top 50 models by name-string grouping

| make | model | vehicle_count |
|---|---|---|
| VOLKSWAGEN | UP! | 62,604 |
| PEUGEOT | 208 | 52,728 |
| VOLKSWAGEN | POLO | 44,333 |
| TOYOTA | AYGO | 43,773 |
| TOYOTA | YARIS | 39,750 |
| CITROËN | C3 | 38,244 |
| KIA | PICANTO | 32,895 |
| CITROËN | C1 | 31,991 |
| FORD | FIESTA | 31,965 |
| VOLKSWAGEN | GOLF | 30,740 |
| HYUNDAI | I10 | 29,175 |
| SKODA | CITIGO | 27,868 |
| OPEL | CORSA | 27,644 |
| RENAULT | Ny Clio | 26,976 |
| HYUNDAI | I20 | 25,514 |
| SKODA | FABIA | 25,197 |
| SKODA | OCTAVIA | 24,510 |
| NISSAN | QASHQAI | 23,722 |
| SUZUKI | SWIFT | 22,549 |
| PEUGEOT | 308 | 21,651 |
| KIA | RIO | 21,547 |
| RENAULT | Captur | 18,881 |
| VOLKSWAGEN | TOURAN | 17,957 |
| PEUGEOT | 107 | 17,675 |
| FORD | KUGA | 16,767 |
| PEUGEOT | 2008 | 16,759 |
| VOLKSWAGEN | PASSAT | 16,112 |
| PEUGEOT | 108 | 15,589 |
| KIA | CEED | 14,992 |
| OPEL | ASTRA | 14,773 |
| FORD | FOCUS | 14,472 |
| CHEVROLET | SPARK | 12,832 |
| FORD | KA | 12,679 |
| MERCEDES-BENZ | C-Klasse | 12,063 |
| SEAT | MII | 11,905 |
| PEUGEOT | 3008 | 11,835 |
| FIAT | 500 | 11,378 |
| TOYOTA | AURIS | 10,970 |
| SUZUKI | VITARA | 9,524 |
| RENAULT | MEGANE | 9,277 |
| SEAT | LEON | 9,206 |
| HYUNDAI | I30 | 9,003 |
| SUZUKI | SX4 S-Cross | 8,987 |
| OPEL | KARL | 8,920 |
| SUZUKI | BALENO | 8,873 |
| VOLKSWAGEN | T-Roc | 8,548 |
| SKODA | OCTAVIA COMBI | 8,432 |
| SUZUKI | Celerio | 8,391 |
| RENAULT | CLIO | 8,289 |
| CITROËN | C4 | 8,280 |
