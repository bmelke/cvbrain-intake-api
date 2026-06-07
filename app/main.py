import os
import re
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel


SERVICE_VERSION = "0.1.0"
SERVICE_NAME = "cvbrain-intake-api"
PRODUCT_NAME = "CVBrain"

app = FastAPI(title="CVBrain Intake API", version=SERVICE_VERSION)


class JobIntakeRequest(BaseModel):
    source_text: str
    source_filename: str = ""
    source_mime_type: str = "text/plain"
    recruiter_notes: str = ""
    locale: str = "es-UY"


def unique(items: List[str]) -> List[str]:
    seen = set()
    output = []
    for item in items:
        clean = re.sub(r"\s+", " ", item.strip())
        key = clean.lower()
        if clean and key not in seen:
            seen.add(key)
            output.append(clean)
    return output


def sentences(text: str) -> List[str]:
    chunks = re.split(r"[\n.;]+", text)
    return unique([chunk.strip(" -•\t") for chunk in chunks if len(chunk.strip()) > 3])


def extract_role_title(text: str) -> str:
    lines = [line.strip(" -•\t\r\n") for line in text.splitlines() if line.strip()]
    if not lines:
        return ""

    first = lines[0]
    first = re.sub(
        r"^(buscamos|se busca|seleccionamos|cargo|puesto)\s*:?\s*",
        "",
        first,
        flags=re.I,
    )
    return first[:120].strip()


def extract_years(text: str) -> Optional[int]:
    patterns = [
        r"(\d+)\s*(?:años|anos|año|ano)\s+de\s+experiencia",
        r"experiencia\s+(?:mínima|minima|de)\s+(\d+)",
        r"mínim[oa]\s+de\s+(\d+)\s*(?:años|anos)",
        r"minim[oa]\s+de\s+(\d+)\s*(?:años|anos)",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            return int(match.group(1))

    return None


def extract_seniority(text: str) -> str:
    lowered = text.lower()

    if "semi senior" in lowered or "semisenior" in lowered or "semi-senior" in lowered:
        return "semi senior"
    if "senior" in lowered:
        return "senior"
    if "junior" in lowered:
        return "junior"

    return ""


def extract_location(text: str) -> Dict[str, Any]:
    lowered = text.lower()
    parts = []

    for loc in ["Montevideo", "Canelones", "Uruguay"]:
        if loc.lower() in lowered:
            parts.append(loc)

    remote_allowed = None
    hybrid_allowed = None

    if "remoto" in lowered or "remote" in lowered:
        remote_allowed = True

    if "híbrido" in lowered or "hibrido" in lowered or "hybrid" in lowered:
        hybrid_allowed = True

    if "presencial" in lowered:
        if remote_allowed is None:
            remote_allowed = False
        if hybrid_allowed is None:
            hybrid_allowed = False

    normalized = ", ".join(unique(parts))

    return {
        "raw": normalized,
        "normalized": normalized,
        "remote_allowed": remote_allowed,
        "hybrid_allowed": hybrid_allowed,
    }


def extract_by_indicators(text: str, indicators: List[str]) -> List[str]:
    output = []

    for sentence in sentences(text):
        lower = sentence.lower()
        if any(indicator in lower for indicator in indicators):
            output.append(sentence)

    return unique(output)


def extract_credentials(text: str) -> Dict[str, List[str]]:
    credential_words = [
        "formación",
        "formacion",
        "título",
        "titulo",
        "licencia",
        "libreta",
        "certificación",
        "certificacion",
    ]

    required_words = [
        "excluyente",
        "imprescindible",
        "requerido",
        "requerida",
        "mínimo",
        "minimo",
        "mínima",
        "minima",
        "indispensable",
    ]

    preferred_words = [
        "deseable",
        "valorable",
        "preferentemente",
        "ideal",
    ]

    required = []
    preferred = []

    for sentence in sentences(text):
        lower = sentence.lower()

        if any(word in lower for word in credential_words):
            if any(word in lower for word in required_words):
                required.append(sentence)
            elif any(word in lower for word in preferred_words):
                preferred.append(sentence)
            else:
                preferred.append(sentence)

    return {
        "required": unique(required),
        "preferred": unique(preferred),
    }


def extract_search_terms(text: str, role_title: str) -> List[str]:
    terms = []

    if role_title:
        terms.append(role_title)

    known_terms = [
        "account manager",
        "ventas",
        "ventas b2b",
        "comercial",
        "dispositivos medicos",
        "dispositivos médicos",
        "salud",
        "crm",
        "administrativo",
        "administrativa",
        "asistente administrativo",
        "asistente administrativa",
        "soporte técnico",
        "soporte tecnico",
        "help desk",
        "logística",
        "logistica",
        "coordinador",
        "coordinadora",
        "inglés",
        "ingles",
        "excel",
        "montevideo",
        "canelones",
    ]

    lowered = text.lower()

    for term in known_terms:
        if term in lowered:
            terms.append(term)

    return unique(terms)


def analyze_text(text: str) -> Dict[str, Any]:
    role_title = extract_role_title(text)
    years = extract_years(text)
    seniority = extract_seniority(text)
    location = extract_location(text)

    must_have = extract_by_indicators(
        text,
        [
            "excluyente",
            "imprescindible",
            "requerido",
            "requerida",
            "mínimo",
            "minimo",
            "mínima",
            "minima",
            "indispensable",
        ],
    )

    should_have = extract_by_indicators(
        text,
        [
            "deseable",
            "valorable",
            "preferentemente",
            "ideal",
        ],
    )

    blockers = extract_by_indicators(
        text,
        [
            "no considerar",
            "sin experiencia no",
            "excluyente no",
        ],
    )

    credentials = extract_credentials(text)
    search_terms = extract_search_terms(text, role_title)

    warnings = []

    if not role_title:
        warnings.append("role_title_empty")

    if not search_terms:
        warnings.append("search_terms_empty")

    confidence = 0.75
    if warnings:
        confidence = 0.45

    return {
        "ok": True,
        "version": SERVICE_VERSION,
        "role_title": role_title,
        "role_family": "",
        "summary": text[:280].strip(),
        "must_have": must_have,
        "should_have": should_have,
        "nice_to_have": [],
        "blockers": blockers,
        "credentials": credentials,
        "experience": {
            "minimum_years": years,
            "seniority": seniority,
        },
        "location": location,
        "search_terms": search_terms,
        "semantic_terms": search_terms,
        "recruiter_questions": [],
        "warnings": warnings,
        "confidence": confidence,
    }


def require_api_key(api_key: Optional[str]) -> None:
    expected = os.getenv("CVBRAIN_INTAKE_API_KEY", "").strip()

    if not expected:
        return

    if not api_key or api_key != expected:
        raise HTTPException(status_code=401, detail="invalid_api_key")


@app.get("/health")
def health() -> Dict[str, Any]:
    return {
        "ok": True,
        "service": SERVICE_NAME,
        "product": PRODUCT_NAME,
        "version": SERVICE_VERSION,
    }


@app.post("/api/job-intake/analyze")
def analyze(
    payload: JobIntakeRequest,
    x_cvbrain_api_key: Optional[str] = Header(default=None),
    x_trabajoaca_api_key: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    api_key = x_cvbrain_api_key or x_trabajoaca_api_key
    require_api_key(api_key)

    text = (payload.source_text or "").strip()

    if not text:
        result = analyze_text("")
        result["ok"] = False
        result["warnings"].append("empty_source_text")
        result["confidence"] = 0.0
        return result

    return analyze_text(text)
