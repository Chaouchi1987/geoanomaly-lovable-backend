# GeoAnomaly Lovable Backend v0.3.0

FastAPI backend for GeoAnomaly Pro.

This version supports Earth Engine OAuth credentials supplied through
EARTHENGINE_CREDENTIALS_JSON, optional service-account JSON, and Google
Cloud Application Default Credentials.

Never commit credentials to GitHub.

Required Render environment variables:
- GOOGLE_CLOUD_PROJECT
- EARTHENGINE_CREDENTIALS_JSON
- CORS_ORIGINS

The backend performs real Earth Engine/Sentinel-2 acquisition and statistics.
It intentionally does not fabricate anomaly targets; target inference is
disabled until validated analysis pipelines are integrated.
