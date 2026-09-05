import json, os, uuid, threading, traceback
from datetime import datetime, timezone
from typing import Any, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, ConfigDict

app = FastAPI(title="GeoAnomaly Lovable Backend", version="0.3.0")

origins = [x.strip() for x in os.getenv("CORS_ORIGINS", "*").split(",") if x.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=False if "*" in origins else True,
    allow_methods=["*"],
    allow_headers=["*"],
)

AOIS: dict[str, dict[str, Any]] = {}
RUNS: dict[str, dict[str, Any]] = {}
EE_LOCK = threading.Lock()
EE_READY = False
EE_INFO: dict[str, Any] = {}

def now():
    return datetime.now(timezone.utc).isoformat()

def _write_oauth_credentials(credentials_json: str) -> str:
    path = "/tmp/earthengine_credentials.json"
    with open(path, "w", encoding="utf-8") as f:
        f.write(credentials_json)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    os.environ["EE_CONFIG_FILE"] = path
    return path

def init_ee():
    global EE_READY, EE_INFO
    with EE_LOCK:
        try:
            import ee
            project = os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("EE_PROJECT")
            oauth_json = os.getenv("EARTHENGINE_CREDENTIALS_JSON")
            service_account_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")

            if not project:
                EE_READY = False
                EE_INFO = {"status":"not_connected","connected":False,"message":"GOOGLE_CLOUD_PROJECT is missing"}
                return EE_INFO

            if oauth_json:
                _write_oauth_credentials(oauth_json)
                credentials = ee.data.get_persistent_credentials()
                if credentials is None:
                    raise RuntimeError("Earth Engine OAuth credentials could not be loaded from EARTHENGINE_CREDENTIALS_JSON")
                ee.Initialize(credentials=credentials, project=project)
                mode = "oauth"
            elif service_account_json:
                info = json.loads(service_account_json)
                if "client_email" not in info:
                    raise ValueError("GOOGLE_SERVICE_ACCOUNT_JSON is missing client_email")
                creds = ee.ServiceAccountCredentials(info["client_email"], key_data=service_account_json)
                ee.Initialize(credentials=creds, project=project)
                mode = "service_account"
            else:
                import google.auth
                creds, _ = google.auth.default()
                ee.Initialize(credentials=creds, project=project)
                mode = "application_default"

            ee.Number(1).add(2).getInfo()
            EE_READY = True
            EE_INFO = {
                "status":"ready","connected":True,"mode":mode,
                "project":project,"message":"Earth Engine initialized successfully"
            }
        except Exception as exc:
            EE_READY = False
            EE_INFO = {"status":"error","connected":False,"message":str(exc)[:700]}
        return EE_INFO

class AOIRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    radius_m: float = Field(..., gt=0, le=500)
    scale_m: float = Field(default=10, gt=0, le=500)
    geometry_type: Optional[str] = "circle"
    shape: Optional[str] = None
    name: Optional[str] = None

class AnalysisStartRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    aoi_id: str
    scale_m: Optional[int] = 10
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    cloud_pct: Optional[float] = 30
    datasets: Optional[list[str]] = None

def bbox(lat, lon, radius_m):
    import math
    dlat = radius_m / 111320.0
    dlon = radius_m / max(1e-9, 111320.0 * abs(math.cos(math.radians(lat))))
    return [lon-dlon, lat-dlat, lon+dlon, lat+dlat]

def geometry_for(aoi):
    import ee
    point = ee.Geometry.Point([aoi["longitude"], aoi["latitude"]])
    if aoi.get("geometry_type") == "square" or aoi.get("shape") == "square":
        return point.buffer(aoi["radius_m"]).bounds()
    return point.buffer(aoi["radius_m"])

@app.get("/")
def root():
    return {"service":"GeoAnomaly Lovable Backend","version":"0.3.0","policy":"No synthetic scientific results"}

@app.get("/health")
def health():
    return {"status":"ok","service":"geoanomaly-backend","version":"0.3.0"}

@app.get("/health/earth-engine")
def ee_health():
    return init_ee()

@app.post("/aoi")
def create_aoi(p: AOIRequest):
    aoi_id = str(uuid.uuid4())
    gtype = p.geometry_type or p.shape or "circle"
    item = {
        "aoi_id":aoi_id,"latitude":p.latitude,"longitude":p.longitude,
        "radius_m":p.radius_m,"scale_m":p.scale_m,"geometry_type":gtype,
        "name":p.name,
        "area_m2": 3.141592653589793*p.radius_m*p.radius_m if gtype=="circle" else (2*p.radius_m)**2,
        "bbox":bbox(p.latitude,p.longitude,p.radius_m),"created_at":now()
    }
    AOIS[aoi_id] = item
    return item

def run_analysis(run_id, request):
    run = RUNS[run_id]
    try:
        state = init_ee()
        if not state.get("connected"):
            run.update(status="failed",stage="failed",progress=1.0,
                       error="Earth Engine is not ready: "+state.get("message","unknown error"),
                       completed_at=now())
            return
        import ee
        aoi = AOIS[request["aoi_id"]]
        geom = geometry_for(aoi)
        run.update(status="running",stage="acquisition",progress=0.1,message="Querying Sentinel-2 collection")
        start = request.get("start_date") or "2024-01-01"
        end = request.get("end_date") or now()[:10]
        cloud = float(request.get("cloud_pct") or 30)
        col = (ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
               .filterBounds(geom).filterDate(start,end)
               .filter(ee.Filter.lte("CLOUDY_PIXEL_PERCENTAGE",cloud)))
        count = int(col.size().getInfo())
        run["datasets"] = [{
            "name":"Sentinel-2 SR Harmonized","family":"optical",
            "provider":"Google Earth Engine / Copernicus",
            "status":"available" if count else "unavailable: no scenes matched filters",
            "resolution_m":10,"scenes":count,
            "note":f"Date range {start} to {end}; cloud threshold {cloud}%"
        }]
        if count == 0:
            run.update(status="completed",stage="completed",progress=1.0,
                       message="No Sentinel-2 scenes matched the selected filters.",completed_at=now())
            return
        run.update(stage="spectral_dem",progress=0.35,message="Computing real AOI summary statistics")
        image = col.median()
        stats = (image.select(["B2","B3","B4","B8","B11"])
                 .reduceRegion(reducer=ee.Reducer.mean(),geometry=geom,
                               scale=int(request.get("scale_m") or 10),
                               maxPixels=1_000_000,bestEffort=True).getInfo())
        run["samples"] = [{"source":"Sentinel-2 SR Harmonized","statistics":stats,"synthetic":False}]
        run["layers"] = []
        run["targets"] = []
        run.update(status="completed",stage="completed",progress=1.0,
                   message="Real Sentinel-2 acquisition completed. No target inference pipeline is enabled yet.",
                   completed_at=now())
    except Exception as exc:
        run.update(status="failed",stage="failed",progress=1.0,error=str(exc),
                   traceback=traceback.format_exc()[-4000:],completed_at=now())

@app.post("/analysis/start")
def analysis_start(p: AnalysisStartRequest):
    if p.aoi_id not in AOIS:
        raise HTTPException(404,"AOI not found")
    run_id = str(uuid.uuid4())
    RUNS[run_id] = {
        "analysis_id":run_id,"status":"queued","stage":"queued","progress":0.0,
        "message":"Analysis queued","started_at":now(),"completed_at":None,
        "datasets":[],"layers":[],"targets":[],"samples":[],"error":None
    }
    t = threading.Thread(target=run_analysis,args=(run_id,p.model_dump()),daemon=True)
    t.start()
    return {"analysis_id":run_id}

def get_run(run_id):
    if run_id not in RUNS: raise HTTPException(404,"Analysis not found")
    return RUNS[run_id]

@app.get("/analysis/{analysis_id}/status")
def analysis_status(analysis_id: str):
    r=get_run(analysis_id)
    return {k:r.get(k) for k in ["analysis_id","status","stage","progress","message","error","started_at","completed_at"]}

@app.get("/analysis/{analysis_id}/datasets")
def datasets(analysis_id: str):
    return {"datasets":get_run(analysis_id)["datasets"]}

@app.get("/analysis/{analysis_id}/layers")
def layers(analysis_id: str):
    return {"layers":get_run(analysis_id)["layers"]}

@app.get("/analysis/{analysis_id}/targets")
def targets(analysis_id: str):
    return {"targets":get_run(analysis_id)["targets"]}

@app.get("/analysis/{analysis_id}/samples")
def samples(analysis_id: str):
    return {"samples":get_run(analysis_id)["samples"],"metadata":{"synthetic":False}}

@app.post("/analysis/test/sentinel2")
def sentinel2_test(body: dict):
    aoi_id=body.get("aoi_id")
    if aoi_id not in AOIS: raise HTTPException(404,"AOI not found")
    state=init_ee()
    if not state.get("connected"): raise HTTPException(503,state.get("message","Earth Engine unavailable"))
    import ee
    aoi=AOIS[aoi_id]; geom=geometry_for(aoi)
    col=ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED").filterBounds(geom)
    count=int(col.size().getInfo())
    return {"aoi_id":aoi_id,"dataset":"COPERNICUS/S2_SR_HARMONIZED","scene_count":count,"synthetic":False}
