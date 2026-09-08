"""Population-based ZIP code clustering for UNG-ZIPPER."""
from typing import List, Optional

AREA_TYPE_RANGES = {
    "rural": (4000, 7000),
    "medium_city": (3000, 5500),
    "large_city": (1500, 4500),
}

class PopulationUnit:
    def __init__(self, name: str, population: int, latitude: Optional[float] = None, longitude: Optional[float] = None):
        self.name = name
        self.population = population
        self.latitude = latitude
        self.longitude = longitude

class ZipCluster:
    def __init__(self):
        self.units: List[PopulationUnit] = []
        self.total_population = 0
        self.flag: Optional[str] = None

    def add(self, unit: PopulationUnit):
        self.units.append(unit)
        self.total_population += unit.population

    def unit_names(self):
        return [u.name for u in self.units]

    def centroid(self):
        coords = [(u.latitude, u.longitude) for u in self.units if u.latitude is not None and u.longitude is not None]
        if not coords:
            return None, None
        lat = sum(c[0] for c in coords) / len(coords)
        lon = sum(c[1] for c in coords) / len(coords)
        return lat, lon

def cluster_units_by_population(units: List[PopulationUnit], area_type: str) -> List[ZipCluster]:
    if area_type not in AREA_TYPE_RANGES:
        raise ValueError(f"area_type must be one of {list(AREA_TYPE_RANGES.keys())}")
    for u in units:
        if u.population <= 0:
            raise ValueError(f"Unit '{u.name}' has non-positive population ({u.population}) - every unit must have population > 0")
    min_pop, max_pop = AREA_TYPE_RANGES[area_type]
    clusters: List[ZipCluster] = []
    current = ZipCluster()

    for unit in units:
        if unit.population > max_pop:
            if current.units:
                if current.total_population < min_pop:
                    current.flag = "undersized"
                elif current.total_population > max_pop:
                    current.flag = "oversized"
                clusters.append(current)
                current = ZipCluster()
            oversized = ZipCluster()
            oversized.add(unit)
            oversized.flag = "oversized"
            clusters.append(oversized)
            continue

        if current.total_population + unit.population > max_pop:
            if current.units:
                if current.total_population < min_pop:
                    current.flag = "undersized"
                elif current.total_population > max_pop:
                    current.flag = "oversized"
                clusters.append(current)
            current = ZipCluster()

        current.add(unit)
        if min_pop <= current.total_population <= max_pop:
            clusters.append(current)
            current = ZipCluster()

    if current.units:
        if current.total_population < min_pop and clusters:
            prev = clusters[-1]
            if prev.total_population + current.total_population <= max_pop and prev.flag != "oversized":
                for u in current.units:
                    prev.add(u)
                prev.flag = None if min_pop <= prev.total_population <= max_pop else prev.flag
            else:
                current.flag = "undersized"
                clusters.append(current)
        else:
            if current.total_population < min_pop:
                current.flag = "undersized"
            clusters.append(current)
    return clusters

def classify_area_type(population: int, is_urban_hint: Optional[bool] = None) -> str:
    if is_urban_hint is False:
        return "rural"
    if population >= 500_000:
        return "large_city"
    if population >= 100_000:
        return "medium_city"
    return "rural"
