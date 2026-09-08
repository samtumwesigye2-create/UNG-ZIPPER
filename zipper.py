"""UNG-ZIPPER national five-digit ZIP code registry."""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, func
from sqlalchemy.orm import Session
from typing import Optional, List

from db import Base, engine, get_db
from auth import require_admin_key
from allocation import PopulationUnit, cluster_units_by_population, AREA_TYPE_RANGES

router = APIRouter(prefix="/zipper", tags=["UNG-ZIPPER"])
STANDARD_RANGE_START = 10000
STANDARD_RANGE_END = 99999
SPECIAL_RANGE_START = 1
SPECIAL_RANGE_END = 999

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

@router.get("/validate/{code}")
def validate_code(code: str, db: Session = Depends(get_db)):
    padded = code.zfill(5) if code.isdigit() else code
    exists = db.query(ZipCode).filter(ZipCode.code == padded).first() is not None
    well_formed = code.isdigit() and len(padded) == 5
    return {"code": code, "well_formed": well_formed, "assigned": exists, "valid": well_formed and exists}

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
