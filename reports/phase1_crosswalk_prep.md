# Phase 1 -> Phase 2 crosswalk prep

In-scope Danish fleet (Personbil, Registreret, 2010-2022, deduped by chassis): **1,778,307 vehicles** across **29,042 variant rows**.

Distinct models grouped by (make_id, model_id): **5,188**

Distinct models grouped by (make_name, model_name) string: **5,140**

Difference: **48** -- this many model_id groupings collapse into fewer distinct name strings, or vice versa (spelling variants of the same model_id, or the same name string covering multiple model_ids).

Top 150 by (make_id, model_id) covers 1,484,195 / 1,778,307 vehicles (83.5% of in-scope fleet).

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
| VOLKSWAGEN | UP! | 62,570 |
| PEUGEOT | 208 | 52,728 |
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
| PEUGEOT | 308 | 21,651 |
| KIA | RIO | 21,547 |
| RENAULT | Captur | 18,881 |
| VOLKSWAGEN | TOURAN | 17,682 |
| PEUGEOT | 107 | 17,675 |
| FORD | KUGA | 16,767 |
| PEUGEOT | 2008 | 16,759 |
| PEUGEOT | 108 | 15,589 |
| VOLKSWAGEN | PASSAT | 15,030 |
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
