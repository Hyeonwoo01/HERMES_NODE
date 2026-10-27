"""Adapter for the National Emergency Medical Center OpenAPI (공공데이터포털).

Service: 국립중앙의료원_전국 응급의료기관 정보 조회 서비스
(https://www.data.go.kr/data/15000563/openapi.do, base URL
``https://apis.data.go.kr/B552657/ErmctInfoInqireService``). Three operations are used:

* ``getEgytListInfoInqire`` — facility list with coordinates (Q0 = 시도, Q1 = 시군구)
* ``getEmrrmRltmUsefulSckbdInfoInqire`` — real-time available beds and equipment
  (STAGE1 = 시도, STAGE2 = 시군구)
* ``getSrsillDissAceptncPosblInfoInqire`` — severe-disease acceptance flags
  (MKioskTy1..28; the 27-group table of the V13 guide)

Field meanings follow the provider's guide (V13) as cross-checked in two
independent open-source clients; confirm against the latest guide before
operational use.

What the public data does NOT contain is labelled as an assumption on every
hospital it produces: historical acceptance rate, transfer-desk response time
and trauma-centre designation. Travel time is estimated from straight-line
distance. Unknown capability flags ("정보미제공", empty) are treated as not
available, so a hospital is never made eligible by missing data.
"""

from __future__ import annotations

import math
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

from .models import Hospital, Origin

BASE_URL = "https://apis.data.go.kr/B552657/ErmctInfoInqireService"
OPS = {
    "directory": "getEgytListInfoInqire",
    "beds": "getEmrrmRltmUsefulSckbdInfoInqire",
    "severe": "getSrsillDissAceptncPosblInfoInqire",
}
KST = ZoneInfo("Asia/Seoul")
SOURCE_LABEL = "국립중앙의료원 응급의료정보 OpenAPI"
SAMPLES = Path(__file__).parent / "samples"

# Values the public data does not provide. Shown on every live hospital.
ASSUMED_ACCEPT_RATE = 0.70
ASSUMED_CONFIRM_MIN = 6.0
ASSUMED_LOAD = 0.5
ASSUMPTIONS = ("과거 수용률 0.70 (공공데이터에 없음 — 가정값)",
               "전원 데스크 응답 6분 (가정값)",
               "이동 시간은 직선거리 기반 추정")

SEVERE_LABELS = {
    "MKioskTy1": "[재관류중재술] 심근경색", "MKioskTy2": "[재관류중재술] 뇌경색",
    "MKioskTy3": "[뇌출혈수술] 거미막하출혈", "MKioskTy4": "[뇌출혈수술] 거미막하출혈 외",
    "MKioskTy11": "[응급내시경] 성인 위장관", "MKioskTy19": "[중증화상] 전문치료",
}

# capability -> (source field, kind, label). kind "flag": Y/N field; "count": available beds > 0.
CAPABILITY_SOURCES: dict[str, tuple[str, str, str]] = {
    "CT": ("hvctayn", "flag", "CT 가용"),
    "CTA": ("hvctayn", "flag", "CT 가용 (CTA는 CT 가용으로 근사)"),
    "MRI": ("hvmriayn", "flag", "MRI 가용"),
    "thrombectomy": ("MKioskTy2", "flag", "뇌경색 재관류중재술 수용"),
    "cath_lab": ("MKioskTy1", "flag", "심근경색 재관류중재술 수용"),
    "endoscopy": ("MKioskTy11", "flag", "성인 위장관 응급내시경 수용"),
    "burn_unit": ("MKioskTy19", "flag", "중증화상 전문치료 수용"),
    "neuro_ICU": ("hvcc", "count", "신경계 중환자실 가용 병상"),
    "ICU": ("hvicc", "count", "일반 중환자실 가용 병상"),
    "OR": ("hvoc", "count", "수술실 가용"),
    "pediatric_ED": ("hv28", "count", "응급실 소아 병상 가용"),
}
# Capabilities with no field in this API; only a regional override list can grant them.
NOT_IN_API = {"trauma_surgery": "외상센터 지정 여부", "PICU": "소아 중환자실"}

PATHWAY_EVIDENCE = {
    "stroke": ("thrombectomy", "neuro_ICU", "CTA"),
    "stemi": ("cath_lab", "ICU"),
    "gi_bleed": ("endoscopy", "ICU"),
    "burn": ("burn_unit", "ICU"),
    "trauma": ("trauma_surgery", "OR", "ICU", "CT"),
    "pediatric": ("pediatric_ED", "CT"),
}

Fetch = Callable[[str, dict], str]


class PublicFeedError(RuntimeError):
    pass


def _clean(v) -> str:
    return (v or "").replace("\xa0", " ").strip()


def flag(v) -> bool | None:
    s = _clean(v)
    if s in ("Y", "가능"):
        return True
    if s in ("N", "N1", "불가", "불가능"):
        return False
    return None  # "정보미제공", empty, anything unexpected


def to_int(v) -> int | None:
    s = _clean(v)
    try:
        return int(float(s))
    except ValueError:
        return None


def parse_items(xml_text: str) -> tuple[list[dict], int]:
    """Items and totalCount of one response page; raises on provider errors."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise PublicFeedError(f"응답이 XML이 아님: {xml_text[:80]!r}") from exc
    reason = root.findtext(".//returnReasonCode")
    if reason:  # gateway-level errors (key not registered, quota exceeded)
        raise PublicFeedError(f"공공데이터포털 오류 {reason}: {_clean(root.findtext('.//returnAuthMsg'))}")
    code = _clean(root.findtext(".//resultCode"))
    if code not in ("00", "0000"):
        raise PublicFeedError(f"resultCode={code} {_clean(root.findtext('.//resultMsg'))}")
    items = [{child.tag: _clean(child.text) for child in item} for item in root.iter("item")]
    total = to_int(root.findtext(".//totalCount")) or len(items)
    return items, total


def urllib_fetch(url: str, params: dict, timeout: float = 15.0) -> str:
    req = urllib.request.Request(url + "?" + urllib.parse.urlencode(params), headers={"Accept": "application/xml"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (fixed https host)
        return resp.read().decode("utf-8")


class NEMCClient:
    def __init__(self, service_key: str, fetch: Fetch | None = None, base_url: str = BASE_URL,
                 rows: int = 100, max_pages: int = 10) -> None:
        """``service_key`` is the *decoded* key from data.go.kr (urlencode is applied here)."""
        if not service_key:
            raise PublicFeedError("서비스 키가 없습니다 (DATA_GO_KR_SERVICE_KEY)")
        self.key = service_key
        self.fetch = fetch or urllib_fetch
        self.base_url = base_url
        self.rows = rows
        self.max_pages = max_pages

    def _all(self, op: str, params: dict) -> list[dict]:
        out: list[dict] = []
        for page in range(1, self.max_pages + 1):
            query = {"serviceKey": self.key, "pageNo": page, "numOfRows": self.rows,
                     **{k: v for k, v in params.items() if v}}
            items, total = parse_items(self.fetch(f"{self.base_url}/{OPS[op]}", query))
            out += items
            if not items or len(out) >= total:
                break
        return out

    def directory(self, sido: str, sigungu: str = "") -> list[dict]:
        return self._all("directory", {"Q0": sido, "Q1": sigungu})

    def beds(self, sido: str, sigungu: str = "") -> list[dict]:
        return self._all("beds", {"STAGE1": sido, "STAGE2": sigungu})

    def severe(self, sido: str, sigungu: str = "") -> list[dict]:
        return self._all("severe", {"STAGE1": sido, "STAGE2": sigungu})


def parse_hvidate(v: str) -> datetime | None:
    try:
        return datetime.strptime(_clean(v), "%Y%m%d%H%M%S").replace(tzinfo=KST)
    except ValueError:
        return None


@dataclass
class Snapshot:
    hospitals: list[Hospital]
    origins: dict[str, Origin]
    fetched_at: datetime
    unknown: dict[str, list[str]] = field(default_factory=dict)  # hpid -> fields reported as unknown
    skipped: list[str] = field(default_factory=list)
    source: str = SOURCE_LABEL


def _project(lat: float, lon: float, lat0: float, lon0: float) -> tuple[float, float]:
    """Equirectangular projection to km around the region centre (fine at city scale)."""
    return ((lon - lon0) * 111.32 * math.cos(math.radians(lat0)), (lat - lat0) * 110.57)


def build_network(directory: list[dict], beds: list[dict], severe: list[dict],
                  now: datetime | None = None,
                  capability_overrides: dict[str, set[str]] | None = None) -> Snapshot:
    """Join the three feeds into Hospital records the ranking engine can use."""
    now = now or datetime.now(timezone.utc)
    overrides = capability_overrides or {}
    coords = {}
    for d in directory:
        lat, lon = to_float(d.get("wgs84Lat")), to_float(d.get("wgs84Lon"))
        if d.get("hpid") and lat is not None and lon is not None:
            coords[d["hpid"]] = (d, lat, lon)
    if not coords:
        raise PublicFeedError("좌표가 있는 응급의료기관이 없습니다 (지역 이름을 확인하세요)")
    lat0 = sum(c[1] for c in coords.values()) / len(coords)
    lon0 = sum(c[2] for c in coords.values()) / len(coords)
    sev = {s.get("hpid"): s for s in severe}

    hospitals, unknown, skipped = [], {}, []
    for b in beds:
        hpid = b.get("hpid")
        if hpid not in coords:
            skipped.append(f"{b.get('dutyName', hpid)}: 좌표 없음")
            continue
        info, lat, lon = coords[hpid]
        row = {**b, **sev.get(hpid, {})}
        caps, evidence, missing = set(), {}, []
        for cap, (key, kind, label) in CAPABILITY_SOURCES.items():
            if kind == "flag":
                ok = flag(row.get(key))
                if ok is None:
                    missing.append(label)
                elif ok:
                    caps.add(cap)
                    evidence[cap] = label
            else:
                n = to_int(row.get(key))
                if n is None:
                    missing.append(label)
                elif n > 0:
                    caps.add(cap)
                    evidence[cap] = f"{label} {n}"
        for cap in overrides.get(hpid, set()):
            caps.add(cap)
            evidence[cap] = f"지역 지정 목록 ({NOT_IN_API.get(cap, cap)})"
        er_beds, er_base = to_int(row.get("hvec")), to_int(row.get("hvs01"))
        if er_beds is None:
            missing.append("응급실 일반 병상")
        load = (1 - max(0, er_beds or 0) / er_base) if er_base else ASSUMED_LOAD
        updated = parse_hvidate(row.get("hvidate", ""))
        age_min = (now - updated).total_seconds() / 60 if updated else 9999.0
        x, y = _project(lat, lon, lat0, lon0)
        notes = {p: "공공데이터: " + ", ".join(evidence[c] for c in cs if c in evidence)
                 for p, cs in PATHWAY_EVIDENCE.items() if any(c in evidence for c in cs)}
        hospitals.append(Hospital(
            hpid, _clean(info.get("dutyName") or b.get("dutyName")), _clean(info.get("dutyEmclsName")) or "응급의료기관",
            round(x, 2), round(y, 2), frozenset(caps),
            beds_available=max(0, er_beds or 0), hist_accept_rate=ASSUMED_ACCEPT_RATE,
            load=round(min(1.0, max(0.0, load)), 2), confirm_delay_min=ASSUMED_CONFIRM_MIN,
            feed_age_min=round(max(0.0, age_min), 1), notes=notes, source=SOURCE_LABEL,
            updated_at=updated.isoformat() if updated else "", assumed=ASSUMPTIONS,
        ))
        if missing:
            unknown[hpid] = missing
    origins = {}
    for hpid, (info, lat, lon) in coords.items():
        x, y = _project(lat, lon, lat0, lon0)
        origins[hpid] = Origin(hpid, f"{_clean(info.get('dutyName'))} (의뢰기관)", round(x, 2), round(y, 2))
    return Snapshot(hospitals, origins, now, unknown, skipped)


def to_float(v) -> float | None:
    try:
        return float(_clean(v))
    except ValueError:
        return None


def load_region(client: NEMCClient, sido: str, sigungu: str = "", now: datetime | None = None,
                capability_overrides: dict[str, set[str]] | None = None) -> Snapshot:
    return build_network(client.directory(sido, sigungu), client.beds(sido, sigungu),
                         client.severe(sido, sigungu), now, capability_overrides)


def sample_client() -> NEMCClient:
    """Client that answers from bundled synthetic XML in the provider's format (no network)."""
    files = {op: (SAMPLES / f"nemc_{name}.xml").read_text(encoding="utf-8") for name, op in OPS.items()}

    def fetch(url: str, params: dict) -> str:
        now = datetime.now(KST)
        return re.sub(r"NOW-(\d+)", lambda m: (now - timedelta(minutes=int(m.group(1)))).strftime("%Y%m%d%H%M%S"),
                      files[url.rsplit("/", 1)[-1]])

    return NEMCClient("sample", fetch=fetch)
