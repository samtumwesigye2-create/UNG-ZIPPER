"""UNG-ZIPPER national five-digit ZIP code registry."""
from __future__ import annotations

import json
import os
import urllib.request
from datetime import datetime, timezone
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, func
from sqlalchemy.orm import Session

from db import Base, engine, get_db, SessionLocal
from auth import require_admin_key
from allocation import PopulationUnit, cluster_units_by_population, AREA_TYPE_RANGES

router = APIRouter(prefix="/zipper", tags=["UNG-ZIPPER"])
STANDARD_RANGE_START = 10000
STANDARD_RANGE_END = 99999
SPECIAL_RANGE_START = 1
SPECIAL_RANGE_END = 999

_SYNC_STATE = {
    "attempted": False,
    "ok": False,
    "imported": 0,
    "skipped": 0,
    "error": None,
    "source": None,
    "synced_at": None,
}


class ZipCode(Base):
    __tablename__ = "zipper_codes"
    id = Column(Integer, primary_key=True)
    code = Column(String, unique=True, index=True)
    district = Column(String, index=True, nullable=True)
    name = Column(String, nullable=True)
    category = Column(String, nullable=True)
    area_type = Column(String)
    population_covered = Column(Integer, nullable=True)
    unit_names = Column(String, nullable=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    protected = Column(Boolean, default=False)
    flag = Column(String, nullable=True)
    created_at = Column(DateTime, server_default=func.now())


Base.metadata.create_all(bind=engine)


def registry_count(db: Session | None = None) -> int:
    own = db is None
    session = db or SessionLocal()
    try:
        return int(session.query(ZipCode).count())
    finally:
        if own:
            session.close()


def sync_state() -> dict:
    return {**_SYNC_STATE, "records": registry_count()}


def _coords_centroid(geometry: dict | None):
    coords = (geometry or {}).get("coordinates")
    points = []

    def walk(value):
        if not isinstance(value, (list, tuple)):
            return
        if len(value) >= 2 and isinstance(value[0], (int, float)) and isinstance(value[1], (int, float)):
            points.append((float(value[0]), float(value[1])))
            return
        for child in value:
            walk(child)

    walk(coords)
    if not points:
        return None, None
    lon = sum(p[0] for p in points) / len(points)
    lat = sum(p[1] for p in points) / len(points)
    return lat, lon


def bootstrap_from_ugamap(force: bool = False) -> dict:
    """Import the live UGAMAP ZIPPER geography into the standalone registry.

    This migrates the already-active map layer into UNG-ZIPPER instead of
    inventing test ZIPs. Existing registry rows are preserved unless force is
    explicitly requested, and duplicate codes are skipped.
    """
    base = os.environ.get("UGAMAP_ZIP_SYNC_URL", "").strip().rstrip("/")
    _SYNC_STATE.update({"attempted": True, "source": base or None, "error": None})
    if not base:
        _SYNC_STATE.update({"ok": registry_count() > 0, "error": "UGAMAP_ZIP_SYNC_URL not configured"})
        return sync_state()

    db = SessionLocal()
    try:
        existing_count = db.query(ZipCode).count()
        if existing_count and not force:
            _SYNC_STATE.update({"ok": True, "imported": 0, "skipped": existing_count, "synced_at": datetime.now(timezone.utc).isoformat()})
            return sync_state()

        req = urllib.request.Request(f"{base}/geography/zipper", headers={"User-Agent": "UNG-ZIPPER/1.0"})
        with urllib.request.urlopen(req, timeout=120) as response:
            payload = json.loads(response.read().decode("utf-8"))

        features = payload.get("features") or []
        if not features:
            raise RuntimeError("UGAMAP returned no ZIPPER geography features")

        imported = 0
        skipped = 0
        for feature in features:
            props = feature.get("properties") or {}
            raw_code = props.get("zip_code") or props.get("zipper_id") or props.get("code")
            code = str(raw_code or "").strip()
            if not code.isdigit():
                skipped += 1
                continue
            code = code.zfill(5)
            numeric = int(code)
            if not (STANDARD_RANGE_START <= numeric <= STANDARD_RANGE_END):
                skipped += 1
                continue
            if db.query(ZipCode).filter(ZipCode.code == code).first():
                skipped += 1
                continue

            lat, lon = _coords_centroid(feature.get("geometry"))
            population = props.get("population")
            try:
                population = int(population) if population is not None else None
            except (TypeError, ValueError):
                population = None

            district = str(props.get("district") or "").strip() or None
            area_type = str(props.get("density_class") or props.get("area_type") or "rural").strip() or "rural"
            state_code = str(props.get("state_code") or "").strip()
            geometry_status = str(props.get("geometry_status") or "").strip()
            flag_parts = [p for p in [geometry_status, f"state:{state_code}" if state_code else ""] if p]

            db.add(ZipCode(
                code=code,
                district=district,
                name=district,
                category="ugamap_live_migration",
                area_type=area_type,
                population_covered=population,
                unit_names=district,
                latitude=lat,
                longitude=lon,
                protected=False,
                flag="; ".join(flag_parts) or None,
            ))
            imported += 1

        db.commit()
        _SYNC_STATE.update({
            "ok": imported > 0 or db.query(ZipCode).count() > 0,
            "imported": imported,
            "skipped": skipped,
            "synced_at": datetime.now(timezone.utc).isoformat(),
        })
        return sync_state()
    except Exception as exc:
        db.rollback()
        _SYNC_STATE.update({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
        return sync_state()
    finally:
        db.close()


def _next_standard_code(db: Session) -> int:
    last = (
        db.query(ZipCode)
        .filter(ZipCode.protected == False)  # noqa: E712
        .order_by(ZipCode.code.desc())
        .first()
    )
    if last and last.code.isdigit():
        return max(int(last.code) + 1, STANDARD_RANGE_START)
    return STANDARD_RANGE_START


class UnitIn(BaseModel):
    name: str
    population: int
    latitude: Optional[float] = None
    longitude: Optional[float] = None


class GenerateIn(BaseModel):
    district: str
    area_type: str
    units: List[UnitIn]


class SpecialCodeIn(BaseModel):
    code: str
    name: str
    category: str


@router.post("/generate")
def generate_codes(payload: GenerateIn, db: Session = Depends(get_db), _=Depends(require_admin_key)):
    if payload.area_type not in AREA_TYPE_RANGES:
        raise HTTPException(400, f"area_type must be one of {list(AREA_TYPE_RANGES.keys())}")
    if not payload.units:
        raise HTTPException(400, "units list cannot be empty")
    units = [PopulationUnit(u.name, u.population, u.latitude, u.longitude) for u in payload.units]
    try:
        clusters = cluster_units_by_population(units, payload.area_type)
    except ValueError as e:
        raise HTTPException(400, str(e))

    created = []
    next_code = _next_standard_code(db)
    if next_code + len(clusters) - 1 > STANDARD_RANGE_END:
        raise HTTPException(400, f"Not enough room in the standard code range: next available is {next_code}, this batch needs {len(clusters)} codes, but the range ends at {STANDARD_RANGE_END}.")

    for cluster in clusters:
        code_str = str(next_code).zfill(5)
        lat, lon = cluster.centroid()
        record = ZipCode(
            code=code_str,
            district=payload.district,
            area_type=payload.area_type,
            population_covered=cluster.total_population,
            unit_names=", ".join(cluster.unit_names()),
            latitude=lat,
            longitude=lon,
            protected=False,
            flag=cluster.flag,
        )
        db.add(record)
        created.append({
            "code": code_str,
            "population_covered": cluster.total_population,
            "units": cluster.unit_names(),
            "flag": cluster.flag,
        })
        next_code += 1
    db.commit()
    flagged = [c for c in created if c["flag"]]
    return {
        "district": payload.district,
        "area_type": payload.area_type,
        "target_range": AREA_TYPE_RANGES[payload.area_type],
        "codes_created": len(created),
        "codes": created,
        "flagged_for_review": flagged,
    }


@router.post("/special")
def register_special_code(payload: SpecialCodeIn, db: Session = Depends(get_db), _=Depends(require_admin_key)):
    if not payload.code.isdigit() or not (SPECIAL_RANGE_START <= int(payload.code) <= SPECIAL_RANGE_END):
        raise HTTPException(400, f"Special codes must be numeric and within {SPECIAL_RANGE_START:05d}-{SPECIAL_RANGE_END:05d}")
    padded_code = payload.code.zfill(5)
    if db.query(ZipCode).filter(ZipCode.code == padded_code).first():
        raise HTTPException(400, "Code already assigned")
    record = ZipCode(code=padded_code, name=payload.name, category=payload.category, area_type="special", protected=True)
    db.add(record)
    db.commit()
    return {"code": record.code, "name": payload.name, "category": payload.category, "protected": True}


@router.post("/sync/ugamap")
def sync_from_ugamap(_=Depends(require_admin_key)):
    return bootstrap_from_ugamap(force=True)


@router.get("/sync/status")
def get_sync_status():
    return sync_state()


@router.get("/validate/{code}")
def validate_code(code: str, db: Session = Depends(get_db)):
    padded = code.zfill(5) if code.isdigit() else code
    exists = db.query(ZipCode).filter(ZipCode.code == padded).first() is not None
    well_formed = code.isdigit() and len(padded) == 5
    return {"code": padded if code.isdigit() else code, "well_formed": well_formed, "assigned": exists, "valid": well_formed and exists}


@router.get("/district/{district}")
def list_district_codes(district: str, db: Session = Depends(get_db)):
    records = db.query(ZipCode).filter(ZipCode.district == district).all()
    return [
        {"code": r.code, "area_type": r.area_type, "population_covered": r.population_covered, "flag": r.flag}
        for r in records
    ]


@router.get("/")
def search_codes(area_type: Optional[str] = None, flagged_only: bool = False, limit: int = 200, db: Session = Depends(get_db)):
    q = db.query(ZipCode)
    if area_type:
        q = q.filter(ZipCode.area_type == area_type)
    if flagged_only:
        q = q.filter(ZipCode.flag.isnot(None))
    records = q.order_by(ZipCode.code).limit(min(limit, 1000)).all()
    return [
        {
            "code": r.code,
            "district": r.district,
            "area_type": r.area_type,
            "population_covered": r.population_covered,
            "protected": r.protected,
            "flag": r.flag,
        }
        for r in records
    ]


@router.get("/{code}")
def resolve_code(code: str, db: Session = Depends(get_db)):
    record = db.query(ZipCode).filter(ZipCode.code == code.zfill(5)).first()
    if not record:
        raise HTTPException(404, "Code not found")
    return {
        "code": record.code,
        "district": record.district,
        "name": record.name,
        "category": record.category,
        "area_type": record.area_type,
        "population_covered": record.population_covered,
        "units": record.unit_names.split(", ") if record.unit_names else None,
        "latitude": record.latitude,
        "longitude": record.longitude,
        "protected": record.protected,
        "flag": record.flag,
    }
