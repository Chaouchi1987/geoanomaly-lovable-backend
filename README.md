# GeoAnomaly Lovable Backend v0.2

This package was revised against the **current Lovable project source code**.

## Current frontend contract supported
- GET /health
- GET /health/earth-engine
- POST /aoi
- POST /analysis/start
- GET /analysis/{id}/status
- GET /analysis/{id}/datasets
- GET /analysis/{id}/layers
- GET /analysis/{id}/targets
- GET /analysis/{id}/samples
- POST /analysis/test/sentinel2

## What is scientifically real in this milestone
When Earth Engine credentials are genuinely configured:
- Sentinel-2 SR Harmonized is queried from Earth Engine.
- Scene count is returned from the real collection.
- AOI band means are computed server-side from real Earth Engine data.
- No synthetic targets are generated.

## What is NOT implemented yet
Target detection/ranking is deliberately disabled. The backend returns an empty target list until validated anomaly, temporal, thermal, geology, and evidence-fusion pipelines are implemented.

## Deployment
Render build command:
pip install -r requirements.txt

Start command:
uvicorn main:app --host 0.0.0.0 --port $PORT

Set GOOGLE_CLOUD_PROJECT and GOOGLE_SERVICE_ACCOUNT_JSON as host secrets.
Never place Earth Engine credentials in Lovable frontend code.
