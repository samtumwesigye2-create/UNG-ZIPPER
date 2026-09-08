# UNG-ZIPPER

National five-digit ZIP code registry for the Uganda National Grid ecosystem. It is intended to be the geographic source of truth that UGAMAP, UGASHIP, and UNG-MERCURY validate and resolve destinations against.

## Population sizing

| Area type | Population per code |
|---|---:|
| rural | 4,000-7,000 |
| medium_city | 3,000-5,500 |
| large_city | 1,500-4,500 |

Clustering is population-based, not geospatial. Inputs should already be in sensible geographic order. Oversized or undersized clusters are flagged for manual review.

## Code ranges

- `00001`-`00999`: special/protected codes, manually registered.
- `10000`-`99999`: standard district/city codes generated sequentially.

## API

Public reads: `GET /zipper/{code}`, `GET /zipper/validate/{code}`, `GET /zipper/district/{district}`, and `GET /zipper/`.

Admin mutations require `X-Admin-Key`: `POST /zipper/generate` and `POST /zipper/special`.

## Production

Set `DATABASE_URL`, `ADMIN_API_KEY`, and optionally `ALLOWED_ORIGINS`. The service exposes `/` and `/health`.
