#!/usr/bin/env python3
"""PMHub Job Radar: conservative, provenance-first public job collection.

The collector intentionally supports only documented public job-board APIs,
public JobPosting JSON-LD pages, a documented search API, and local imports.
It never submits applications and never accepts login cookies or auth headers.
"""

from __future__ import annotations

import argparse
import copy
import csv
import datetime as dt
import email.utils
import hashlib
import html
import http.client
import io
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import sqlite3
import ssl
import sys
import tempfile
import time
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
import uuid
import xml.etree.ElementTree as ET


SCHEMA_VERSION = "1.0"
USER_AGENT = "PMHubJobRadar/1.0 (+local, read-only job research)"

DOCUMENTED_API_HOSTS = {
    "boards-api.greenhouse.io",
    "api.lever.co",
    "api.eu.lever.co",
    "api.ashbyhq.com",
    "api.smartrecruiters.com",
    "customsearch.googleapis.com",
}

# Direct automated access is fail-closed for these third-party platforms. A
# user-provided or platform-authorized export can still use manual_import.
RESTRICTED_DOMAIN_SUFFIXES = {
    "zhipin.com",
    "lagou.com",
    "51job.com",
    "zhaopin.com",
    "liepin.com",
    "linkedin.com",
    "indeed.com",
    "glassdoor.com",
}

TRACKING_QUERY_NAMES = {
    "source",
    "src",
    "ref",
    "referrer",
    "gh_src",
    "lever-source",
    "lever-origin",
    "trk",
    "trackingid",
    "jobsource",
    "sourcetype",
}

SENSITIVE_QUERY_NAMES = {
    "key",
    "api_key",
    "access_token",
    "token",
    "cx",
    "client_secret",
    "signature",
    "sig",
}

MAX_RETRY_SLEEP_SECONDS = 30.0
MAX_ROBOTS_INTERVAL_SECONDS = 60.0
DEFAULT_MAX_PAGES = 100

SENSITIVE_CONFIG_KEYS = {
    "authorization",
    "cookie",
    "cookies",
    "headers",
    "password",
    "username",
    "api_key",
    "access_token",
    "bearer_token",
    "token",
}

SOURCE_PRIORITY = {
    "official_ats": 0,
    "company_site": 1,
    "user_supplied": 2,
    "search_api": 3,
}

PROVIDER_REQUIREMENTS = {
    "greenhouse": ("company", "board_token"),
    "lever": ("company", "site"),
    "ashby": ("company", "board"),
    "smartrecruiters": ("company", "company_identifier"),
    "jsonld": ("company", "urls"),
    "sitemap_jsonld": ("company", "sitemap_url", "include_regex"),
    "google_cse": ("query", "api_key_env", "cx_env"),
    "manual_import": ("path",),
}

DEFAULTS: Dict[str, Any] = {
    "fresh_days": 7,
    "stale_days": 30,
    "close_after_misses": 2,
    "request_interval_seconds": 1.0,
    "timeout_seconds": 15.0,
    "max_response_bytes": 8 * 1024 * 1024,
    "max_retries": 2,
}

GOOGLE_CSE_ENV_VARS = {
    "api_key_env": "PMHUB_GOOGLE_CSE_KEY",
    "cx_env": "PMHUB_GOOGLE_CSE_CX",
}


class ConfigError(ValueError):
    pass


class FetchError(RuntimeError):
    pass


class ParseError(RuntimeError):
    pass


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def isoformat(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def parse_datetime(value: Any) -> Optional[dt.datetime]:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        timestamp = float(value)
        if timestamp > 100_000_000_000:
            timestamp /= 1000.0
        try:
            return dt.datetime.fromtimestamp(timestamp, tz=dt.timezone.utc)
        except (ValueError, OSError, OverflowError):
            return None
    text = str(value).strip()
    if not text:
        return None
    if re.fullmatch(r"\d{10,13}", text):
        return parse_datetime(int(text))
    candidate = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = dt.datetime.fromisoformat(candidate)
    except ValueError:
        try:
            parsed = dt.datetime.strptime(text[:10], "%Y-%m-%d")
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def normalize_unicode(value: Any) -> str:
    return unicodedata.normalize("NFKC", str(value or ""))


def normalize_space(value: Any) -> str:
    return re.sub(r"\s+", " ", normalize_unicode(value)).strip()


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: List[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.parts.append(data)


def strip_html(value: Any) -> str:
    text = html.unescape(str(value or ""))
    # Some ATS payloads encode HTML twice.
    if "&lt;" in text or "&amp;" in text:
        text = html.unescape(text)
    parser = _TextExtractor()
    try:
        parser.feed(text)
        parser.close()
        return normalize_space(" ".join(parser.parts))
    except Exception:
        return normalize_space(re.sub(r"<[^>]+>", " ", text))


def _host_matches(host: str, suffixes: Iterable[str]) -> bool:
    host = host.rstrip(".").casefold()
    return any(host == suffix or host.endswith("." + suffix) for suffix in suffixes)


def is_restricted_host(host: str) -> bool:
    return _host_matches(host, RESTRICTED_DOMAIN_SUFFIXES)


def validate_url_static(url: str, *, allow_restricted: bool = False) -> str:
    try:
        parsed = urllib.parse.urlsplit(url)
    except ValueError as exc:
        raise ConfigError(f"invalid URL: {url!r}: {exc}") from exc
    if parsed.scheme.casefold() not in {"http", "https"}:
        raise ConfigError(f"only http/https URLs are allowed: {url!r}")
    if not parsed.hostname:
        raise ConfigError(f"URL must include a hostname: {url!r}")
    if parsed.username is not None or parsed.password is not None:
        raise ConfigError(f"userinfo is forbidden in URLs: {url!r}")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ConfigError(f"invalid URL port: {url!r}") from exc
    if port is not None and not 1 <= port <= 65535:
        raise ConfigError(f"invalid URL port: {url!r}")
    host = parsed.hostname.rstrip(".").casefold()
    if host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
        raise ConfigError(f"local hosts are forbidden: {host}")
    try:
        literal = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        literal = None
    if literal is not None and not literal.is_global:
        raise ConfigError(f"non-public IP addresses are forbidden: {host}")
    if not allow_restricted and is_restricted_host(host):
        raise ConfigError(
            f"direct automated access to restricted recruiting platform is disabled: {host}"
        )
    return host


def canonicalize_url(url: Any) -> str:
    text = normalize_space(url)
    if not text:
        return ""
    try:
        parsed = urllib.parse.urlsplit(text)
    except ValueError:
        return text
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.hostname:
        return text
    scheme = parsed.scheme.casefold()
    host = parsed.hostname.rstrip(".").casefold()
    try:
        port = parsed.port
    except ValueError:
        port = None
    netloc = host
    if ":" in host and not host.startswith("["):
        netloc = f"[{host}]"
    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        netloc += f":{port}"
    path = urllib.parse.quote(urllib.parse.unquote(parsed.path or "/"), safe="/%:@!$&'()*+,;=-._~")
    if path != "/":
        path = path.rstrip("/") or "/"
    kept: List[Tuple[str, str]] = []
    for key, value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True):
        lowered = key.casefold()
        if lowered.startswith("utm_") or lowered in TRACKING_QUERY_NAMES:
            continue
        kept.append((key, value))
    query = urllib.parse.urlencode(sorted(kept), doseq=True)
    return urllib.parse.urlunsplit((scheme, netloc, path, query, ""))


def redact_url(url: str) -> str:
    try:
        parsed = urllib.parse.urlsplit(url)
    except ValueError:
        return url
    redacted = []
    for key, value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True):
        if key.casefold() in SENSITIVE_QUERY_NAMES:
            value = "<redacted>"
        redacted.append((key, value))
    return urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urllib.parse.urlencode(redacted), "")
    )


def safe_error_message(error: BaseException) -> str:
    message = str(error)
    for environment_name in GOOGLE_CSE_ENV_VARS.values():
        secret = os.environ.get(environment_name)
        if secret:
            message = message.replace(secret, "<redacted>")
    query_names = "|".join(re.escape(name) for name in sorted(SENSITIVE_QUERY_NAMES))
    message = re.sub(
        rf"(?i)([?&](?:{query_names})=)[^&\s]+",
        r"\1<redacted>",
        message,
    )
    return message[:2000]


def hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _hash_norm(value: Any) -> str:
    return normalize_space(value).casefold()


def location_from_raw(
    raw: Any,
    *,
    city: Any = None,
    region: Any = None,
    country: Any = None,
    remote: Any = None,
) -> Dict[str, Any]:
    raw_text = normalize_space(raw)
    city_text = normalize_space(city) or None
    region_text = normalize_space(region) or None
    country_text = normalize_space(country) or None
    if remote is None:
        lowered = raw_text.casefold()
        remote_value = bool(re.search(r"\bremote\b|远程|居家", lowered))
    else:
        remote_value = bool(remote)
    return {
        "raw": raw_text,
        "city": city_text,
        "region": region_text,
        "country": country_text,
        "remote": remote_value,
    }


def normalize_locations(values: Any) -> List[Dict[str, Any]]:
    if values is None:
        return []
    if isinstance(values, (str, dict)):
        values = [values]
    output: List[Dict[str, Any]] = []
    seen = set()
    for item in values:
        if isinstance(item, dict):
            location = location_from_raw(
                item.get("raw") or item.get("name") or item.get("location") or item.get("city"),
                city=item.get("city"),
                region=item.get("region"),
                country=item.get("country"),
                remote=item.get("remote"),
            )
        else:
            location = location_from_raw(item)
        key = tuple(_hash_norm(location.get(field)) for field in ("raw", "city", "region", "country"))
        if key == ("", "", "", "") or key in seen:
            continue
        seen.add(key)
        output.append(location)
    return output


def content_fingerprint(job: Dict[str, Any]) -> str:
    locations = sorted(
        "|".join(
            _hash_norm(loc.get(field)) for field in ("raw", "city", "region", "country")
        )
        for loc in job.get("locations", [])
    )
    description = _hash_norm(job.get("description_text"))
    payload = {
        "company": _hash_norm(job.get("company")),
        "title": _hash_norm(job.get("title")),
        "locations": locations,
        "description": description,
    }
    # Incomplete discovery records must not collapse solely because their title
    # and company happen to match.
    if not description:
        payload["canonical_url"] = job.get("canonical_url", "")
    return hash_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def stable_job_uid(job: Dict[str, Any], source_id: str) -> str:
    if job.get("canonical_url"):
        identity = "url:" + job["canonical_url"]
    elif job.get("external_id"):
        identity = f"external:{source_id}:{job['external_id']}"
    else:
        identity = "content:" + job.get("content_fingerprint", "")
    return "job_" + hash_text(identity)[:24]


def _freshness(
    job: Dict[str, Any], now: dt.datetime, defaults: Dict[str, Any]
) -> Tuple[str, List[str]]:
    flags: List[str] = []
    expires = parse_datetime(job.get("expires_at"))
    if expires is not None and expires < now:
        return "expired", flags
    reference = parse_datetime(job.get("posted_at")) or parse_datetime(job.get("updated_at"))
    if reference is None:
        return "unknown", ["date_unknown"]
    age_days = (now - reference).total_seconds() / 86400
    if age_days < -1:
        flags.append("future_date")
    if age_days <= float(defaults["fresh_days"]):
        return "fresh", flags
    if age_days <= float(defaults["stale_days"]):
        return "aging", flags
    return "stale", flags


def _quality(job: Dict[str, Any], source_class: str) -> Tuple[int, List[str]]:
    score = {
        "official_ats": 45,
        "company_site": 40,
        "user_supplied": 25,
        "search_api": 15,
    }.get(source_class, 10)
    flags: List[str] = []
    if job.get("title"):
        score += 10
    else:
        flags.append("missing_title")
    if job.get("company"):
        score += 8
    else:
        flags.append("missing_company")
    if job.get("canonical_url"):
        score += 8
    else:
        flags.append("missing_job_url")
    description = job.get("description_text") or ""
    if len(description) >= 120:
        score += 15
    elif description:
        score += 5
        flags.append("description_short")
    else:
        flags.append("missing_description")
    if job.get("locations"):
        score += 5
    else:
        flags.append("missing_location")
    if job.get("posted_at") or job.get("updated_at"):
        score += 5
    if job.get("external_id"):
        score += 4
    if re.search(
        r"押金|保证金|培训费|入职费|application fee|pay (?:a|the) fee",
        description,
        re.IGNORECASE,
    ):
        flags.append("suspicious_payment_language_review")
        score -= 10
    return max(0, min(100, score)), flags


def finalize_job(
    raw_job: Dict[str, Any],
    *,
    source: Dict[str, Any],
    source_class: str,
    fetched_via: str,
    source_url: str,
    now: dt.datetime,
    defaults: Dict[str, Any],
    extra_flags: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    url_flags: List[str] = []

    def safe_output_url(value: Any, field_name: str) -> Optional[str]:
        candidate = normalize_space(value)
        if not candidate:
            return None
        try:
            # User-authorized exports may legitimately point at otherwise
            # restricted recruiting platforms, but never at local/private
            # literals, non-HTTP schemes, or URLs carrying userinfo.
            validate_url_static(candidate, allow_restricted=source_class == "user_supplied")
        except ConfigError:
            url_flags.append(f"unsafe_{field_name}_removed")
            return None
        return candidate

    safe_job_url = safe_output_url(raw_job.get("job_url"), "job_url")
    safe_apply_url = safe_output_url(raw_job.get("apply_url"), "apply_url")
    job = {
        "schema_version": SCHEMA_VERSION,
        "job_uid": "",
        "external_id": normalize_space(raw_job.get("external_id")) or None,
        "company": normalize_space(raw_job.get("company") or source.get("company")),
        "title": normalize_space(raw_job.get("title")),
        "description_text": normalize_space(raw_job.get("description_text")),
        "department": normalize_space(raw_job.get("department")) or None,
        "team": normalize_space(raw_job.get("team")) or None,
        "seniority": normalize_space(raw_job.get("seniority")) or None,
        "employment_type": normalize_space(raw_job.get("employment_type")) or None,
        "workplace_type": normalize_space(raw_job.get("workplace_type")).casefold() or None,
        "locations": normalize_locations(raw_job.get("locations")),
        "salary": raw_job.get("salary") if isinstance(raw_job.get("salary"), dict) else None,
        "posted_at": normalize_space(raw_job.get("posted_at")) or None,
        "updated_at": normalize_space(raw_job.get("updated_at")) or None,
        "expires_at": normalize_space(raw_job.get("expires_at")) or None,
        "job_url": safe_job_url or "",
        "apply_url": safe_apply_url,
        "canonical_url": "",
        "language": normalize_space(raw_job.get("language")) or None,
        "status": "open" if source_class in {"official_ats", "company_site"} else "unknown",
        "freshness_status": "unknown",
        "quality_score": 0,
        "quality_flags": [],
        "content_fingerprint": "",
        "provenance": [],
    }
    job["canonical_url"] = canonicalize_url(job["job_url"] or job["apply_url"] or "")
    freshness, freshness_flags = _freshness(job, now, defaults)
    job["freshness_status"] = freshness
    if freshness == "expired":
        job["status"] = "expired"
    job["content_fingerprint"] = content_fingerprint(job)
    job["job_uid"] = stable_job_uid(job, source["id"])
    score, quality_flags = _quality(job, source_class)
    job["quality_score"] = score
    all_flags = list(extra_flags or []) + url_flags + freshness_flags + quality_flags
    job["quality_flags"] = sorted(set(flag for flag in all_flags if flag))
    job["provenance"] = [
        {
            "source_id": source["id"],
            "provider": source["provider"],
            "source_class": source_class,
            "source_url": redact_url(source_url),
            "job_canonical_url": job["canonical_url"] or None,
            "external_id": job["external_id"],
            "content_fingerprint": job["content_fingerprint"],
            "observed_at": isoformat(now),
            "fetched_via": fetched_via,
        }
    ]
    return job


def _source_class(job: Dict[str, Any]) -> str:
    classes = [p.get("source_class", "") for p in job.get("provenance", [])]
    return min(classes, key=lambda item: SOURCE_PRIORITY.get(item, 99), default="")


def _recompute_merged(job: Dict[str, Any], now: dt.datetime, defaults: Dict[str, Any]) -> None:
    job["locations"] = normalize_locations(job.get("locations"))
    job["content_fingerprint"] = content_fingerprint(job)
    freshness, freshness_flags = _freshness(job, now, defaults)
    job["freshness_status"] = freshness
    if freshness == "expired":
        job["status"] = "expired"
    score, quality_flags = _quality(job, _source_class(job))
    job["quality_score"] = score
    job["quality_flags"] = sorted(
        set(job.get("quality_flags", [])) | set(freshness_flags) | set(quality_flags)
    )


def merge_jobs(
    left: Dict[str, Any], right: Dict[str, Any], now: dt.datetime, defaults: Dict[str, Any]
) -> Dict[str, Any]:
    left_rank = SOURCE_PRIORITY.get(_source_class(left), 99)
    right_rank = SOURCE_PRIORITY.get(_source_class(right), 99)
    base, other = (left, right) if left_rank <= right_rank else (right, left)
    merged = copy.deepcopy(base)
    scalar_fields = (
        "external_id",
        "company",
        "title",
        "department",
        "team",
        "seniority",
        "employment_type",
        "workplace_type",
        "salary",
        "posted_at",
        "updated_at",
        "expires_at",
        "job_url",
        "apply_url",
        "canonical_url",
        "language",
    )
    for field_name in scalar_fields:
        if not merged.get(field_name) and other.get(field_name):
            merged[field_name] = copy.deepcopy(other[field_name])
    if len(other.get("description_text") or "") > len(merged.get("description_text") or ""):
        merged["description_text"] = other["description_text"]
    merged["locations"] = list(merged.get("locations", [])) + list(other.get("locations", []))
    provenance = list(merged.get("provenance", []))
    seen = {
        (p.get("source_id"), p.get("source_url"), p.get("provider")) for p in provenance
    }
    for item in other.get("provenance", []):
        key = (item.get("source_id"), item.get("source_url"), item.get("provider"))
        if key not in seen:
            provenance.append(copy.deepcopy(item))
            seen.add(key)
    merged["provenance"] = provenance
    merged["quality_flags"] = sorted(
        set(merged.get("quality_flags", []))
        | set(other.get("quality_flags", []))
        | {"deduplicated_multi_source"}
    )
    # Keep the preferred source's UID stable even if the merged description is longer.
    _recompute_merged(merged, now, defaults)
    return merged


def _source_identity_map(job: Dict[str, Any]) -> Dict[str, set]:
    identities: Dict[str, set] = {}
    for provenance in job.get("provenance", []):
        if not isinstance(provenance, dict):
            continue
        source_id = normalize_space(provenance.get("source_id"))
        if not source_id:
            continue
        tokens = identities.setdefault(source_id, set())
        canonical = normalize_space(provenance.get("job_canonical_url"))
        external_id = normalize_space(provenance.get("external_id"))
        if canonical:
            tokens.add("url:" + canonical)
        if external_id:
            tokens.add("external:" + external_id)
    return identities


def _fingerprint_merge_allowed(left: Dict[str, Any], right: Dict[str, Any]) -> bool:
    left_identities = _source_identity_map(left)
    right_identities = _source_identity_map(right)
    for source_id in set(left_identities) & set(right_identities):
        # Same-source records need at least one matching stable identity. Exact
        # text alone is not enough: one company can publish multiple identical
        # headcounts under different IDs and URLs.
        if not (left_identities[source_id] & right_identities[source_id]):
            return False
    return True


def dedupe_jobs(
    jobs: Sequence[Dict[str, Any]], now: dt.datetime, defaults: Dict[str, Any]
) -> List[Dict[str, Any]]:
    ordered = sorted(
        (copy.deepcopy(job) for job in jobs),
        key=lambda job: (
            SOURCE_PRIORITY.get(_source_class(job), 99),
            job.get("canonical_url", ""),
            job.get("content_fingerprint", ""),
        ),
    )
    output: List[Dict[str, Any]] = []
    url_index: Dict[str, int] = {}
    fingerprint_index: Dict[str, List[int]] = {}
    for job in ordered:
        match_index: Optional[int] = None
        canonical = job.get("canonical_url")
        fingerprint = job.get("content_fingerprint")
        if canonical and canonical in url_index:
            match_index = url_index[canonical]
        elif fingerprint and fingerprint in fingerprint_index:
            for candidate_index in fingerprint_index[fingerprint]:
                if _fingerprint_merge_allowed(output[candidate_index], job):
                    match_index = candidate_index
                    break
            if match_index is None:
                job["quality_flags"] = sorted(
                    set(job.get("quality_flags", []))
                    | {"possible_duplicate_same_source_identity_conflict"}
                )
                for candidate_index in fingerprint_index[fingerprint]:
                    output[candidate_index]["quality_flags"] = sorted(
                        set(output[candidate_index].get("quality_flags", []))
                        | {"possible_duplicate_same_source_identity_conflict"}
                    )
        if match_index is None:
            output.append(job)
            match_index = len(output) - 1
        else:
            output[match_index] = merge_jobs(output[match_index], job, now, defaults)
        merged = output[match_index]
        for alias in (
            merged.get("canonical_url"),
            job.get("canonical_url"),
        ):
            if alias:
                url_index[alias] = match_index
        for fp in (
            merged.get("content_fingerprint"),
            job.get("content_fingerprint"),
        ):
            if fp:
                indices = fingerprint_index.setdefault(fp, [])
                if match_index not in indices:
                    indices.append(match_index)
    return output


class BaseFetcher:
    mode = "base"

    def get(self, url: str, *, documented_api: bool = False) -> bytes:
        raise NotImplementedError


class FixtureFetcher(BaseFetcher):
    mode = "fixtures"

    def __init__(self, fixture_dir: Path, max_response_bytes: int) -> None:
        self.fixture_dir = fixture_dir.resolve()
        mapping_path = self.fixture_dir / "http_map.json"
        try:
            self.mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ConfigError(f"cannot read fixture map {mapping_path}: {exc}") from exc
        if not isinstance(self.mapping, dict):
            raise ConfigError("fixture http_map.json must be an object")
        self.max_response_bytes = max_response_bytes

    def get(self, url: str, *, documented_api: bool = False) -> bytes:
        key = redact_url(url)
        relative = self.mapping.get(key)
        if not isinstance(relative, str):
            raise FetchError(f"fixture URL is not mapped: {key}")
        candidate = (self.fixture_dir / relative).resolve()
        try:
            candidate.relative_to(self.fixture_dir)
        except ValueError as exc:
            raise FetchError(f"fixture path escapes fixture directory: {relative}") from exc
        try:
            data = candidate.read_bytes()
        except OSError as exc:
            raise FetchError(f"cannot read fixture {candidate}: {exc}") from exc
        if len(data) > self.max_response_bytes:
            raise FetchError(f"fixture response exceeds {self.max_response_bytes} bytes: {candidate}")
        return data


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, validator: Any, documented_api: bool) -> None:
        super().__init__()
        self.validator = validator
        self.documented_api = documented_api

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> Optional[urllib.request.Request]:
        self.validator(newurl, documented_api=self.documented_api)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _connect_pinned_socket(
    addresses: Sequence[str],
    port: int,
    timeout: Any,
    source_address: Optional[Tuple[str, int]],
) -> socket.socket:
    """Connect to an already validated literal IP without another DNS lookup."""
    last_error: Optional[OSError] = None
    for address in addresses:
        parsed = ipaddress.ip_address(address)
        family = socket.AF_INET6 if parsed.version == 6 else socket.AF_INET
        connection = socket.socket(family, socket.SOCK_STREAM)
        try:
            if timeout is not socket._GLOBAL_DEFAULT_TIMEOUT:
                connection.settimeout(timeout)
            if source_address:
                bind_address: Any = source_address
                if family == socket.AF_INET6 and len(source_address) == 2:
                    bind_address = (source_address[0], source_address[1], 0, 0)
                connection.bind(bind_address)
            target: Any = (address, port, 0, 0) if family == socket.AF_INET6 else (address, port)
            connection.connect(target)
            return connection
        except OSError as exc:
            last_error = exc
            connection.close()
    if last_error is not None:
        raise last_error
    raise OSError("validated DNS result contained no connectable addresses")


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, *args: Any, pinned_addresses: Sequence[str], **kwargs: Any) -> None:
        self._pinned_addresses = tuple(pinned_addresses)
        super().__init__(*args, **kwargs)

    def connect(self) -> None:
        self.sock = _connect_pinned_socket(
            self._pinned_addresses, self.port, self.timeout, self.source_address
        )
        if self._tunnel_host:
            self._tunnel()


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, *args: Any, pinned_addresses: Sequence[str], **kwargs: Any) -> None:
        self._pinned_addresses = tuple(pinned_addresses)
        super().__init__(*args, **kwargs)

    def connect(self) -> None:
        self.sock = _connect_pinned_socket(
            self._pinned_addresses, self.port, self.timeout, self.source_address
        )
        if self._tunnel_host:
            self._tunnel()
            server_hostname = self._tunnel_host
        else:
            server_hostname = self.host
        # Keep certificate and hostname verification bound to the original
        # hostname even though the TCP connection is pinned to a literal IP.
        self.sock = self._context.wrap_socket(self.sock, server_hostname=server_hostname)


class _PinnedHTTPHandler(urllib.request.HTTPHandler):
    def __init__(self, fetcher: "NetworkFetcher", documented_api: bool) -> None:
        super().__init__()
        self.fetcher = fetcher
        self.documented_api = documented_api

    def http_open(self, request: urllib.request.Request) -> Any:
        _, addresses = self.fetcher._prepare_connection(
            request.full_url, documented_api=self.documented_api
        )

        def connection_factory(host: str, **kwargs: Any) -> _PinnedHTTPConnection:
            return _PinnedHTTPConnection(host, pinned_addresses=addresses, **kwargs)

        return self.do_open(connection_factory, request)


class _PinnedHTTPSHandler(urllib.request.HTTPSHandler):
    def __init__(self, fetcher: "NetworkFetcher", documented_api: bool) -> None:
        super().__init__(context=ssl.create_default_context())
        self.fetcher = fetcher
        self.documented_api = documented_api

    def https_open(self, request: urllib.request.Request) -> Any:
        _, addresses = self.fetcher._prepare_connection(
            request.full_url, documented_api=self.documented_api
        )

        def connection_factory(host: str, **kwargs: Any) -> _PinnedHTTPSConnection:
            return _PinnedHTTPSConnection(host, pinned_addresses=addresses, **kwargs)

        return self.do_open(
            connection_factory,
            request,
            context=self._context,
        )


class NetworkFetcher(BaseFetcher):
    mode = "live"

    def __init__(self, defaults: Dict[str, Any]) -> None:
        self.timeout = float(defaults["timeout_seconds"])
        self.max_response_bytes = int(defaults["max_response_bytes"])
        self.max_retries = int(defaults["max_retries"])
        self.request_interval = float(defaults["request_interval_seconds"])
        self.last_request_by_host: Dict[str, float] = {}
        self.robots_interval_by_host: Dict[str, float] = {}
        self.robots_cache: Dict[str, urllib.robotparser.RobotFileParser] = {}

    def _resolve_target(
        self, url: str, *, documented_api: bool
    ) -> Tuple[str, Tuple[str, ...]]:
        try:
            host = validate_url_static(url, allow_restricted=documented_api)
        except ConfigError as exc:
            raise FetchError(str(exc)) from exc
        if documented_api and host not in DOCUMENTED_API_HOSTS:
            raise FetchError(f"undocumented API host is forbidden: {host}")
        parsed_url = urllib.parse.urlsplit(url)
        port = parsed_url.port or (443 if parsed_url.scheme.casefold() == "https" else 80)
        try:
            addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except socket.gaierror as exc:
            raise FetchError(f"DNS lookup failed for {host}: {exc}") from exc
        resolved = {item[4][0].split("%", 1)[0] for item in addresses}
        if not resolved:
            raise FetchError(f"DNS lookup returned no addresses for {host}")
        for address in resolved:
            try:
                parsed = ipaddress.ip_address(address)
            except ValueError as exc:
                raise FetchError(f"invalid resolved address for {host}: {address}") from exc
            if not parsed.is_global:
                raise FetchError(f"non-public resolved address is forbidden for {host}: {address}")
        return host, tuple(sorted(resolved))

    def _validate_target(self, url: str, *, documented_api: bool) -> str:
        host, _ = self._resolve_target(url, documented_api=documented_api)
        return host

    def _prepare_connection(
        self, url: str, *, documented_api: bool
    ) -> Tuple[str, Tuple[str, ...]]:
        host, addresses = self._resolve_target(url, documented_api=documented_api)
        self._rate_limit(host)
        return host, addresses

    def _rate_limit(self, host: str) -> None:
        last = self.last_request_by_host.get(host)
        interval = max(self.request_interval, self.robots_interval_by_host.get(host, 0.0))
        if last is not None:
            remaining = interval - (time.monotonic() - last)
            if remaining > 0:
                time.sleep(remaining)
        self.last_request_by_host[host] = time.monotonic()

    @staticmethod
    def _retry_delay(error: urllib.error.HTTPError, attempt: int) -> float:
        retry_after = error.headers.get("Retry-After") if error.headers else None
        if retry_after:
            try:
                return max(0.0, float(retry_after))
            except ValueError:
                parsed = email.utils.parsedate_to_datetime(retry_after)
                if parsed:
                    if parsed.tzinfo is None:
                        parsed = parsed.replace(tzinfo=dt.timezone.utc)
                    return max(0.0, (parsed - utc_now()).total_seconds())
        return min(8.0, 2.0**attempt)

    def _raw_get(
        self,
        url: str,
        *,
        documented_api: bool,
        enforce_redirect_robots: bool = True,
    ) -> bytes:
        self._validate_target(url, documented_api=documented_api)

        def validate_redirect(new_url: str, *, documented_api: bool) -> str:
            host = self._validate_target(new_url, documented_api=documented_api)
            if not documented_api and enforce_redirect_robots:
                parser = self._robots_parser(new_url)
                if not parser.can_fetch(USER_AGENT, new_url):
                    raise FetchError(f"robots.txt disallows redirect target {redact_url(new_url)}")
                self._apply_robots_rate_policy(new_url, parser)
            return host

        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            _PinnedHTTPHandler(self, documented_api),
            _PinnedHTTPSHandler(self, documented_api),
            _SafeRedirectHandler(validate_redirect, documented_api),
        )
        request = urllib.request.Request(
            url,
            method="GET",
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json, application/ld+json, application/xml, text/xml, text/html;q=0.9",
            },
        )
        last_error: Optional[BaseException] = None
        for attempt in range(self.max_retries + 1):
            try:
                with opener.open(request, timeout=self.timeout) as response:
                    final_url = response.geturl()
                    self._validate_target(final_url, documented_api=documented_api)
                    data = response.read(self.max_response_bytes + 1)
                    if len(data) > self.max_response_bytes:
                        raise FetchError(
                            f"response exceeds {self.max_response_bytes} bytes: {redact_url(final_url)}"
                        )
                    return data
            except urllib.error.HTTPError as exc:
                last_error = exc
                if exc.code not in {429, 500, 502, 503, 504} or attempt >= self.max_retries:
                    break
                delay = self._retry_delay(exc, attempt)
                if delay > MAX_RETRY_SLEEP_SECONDS:
                    raise FetchError(
                        f"server requested Retry-After={delay:.0f}s; source stopped instead of retrying early"
                    ) from exc
                time.sleep(delay)
            except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    break
                time.sleep(min(8.0, 2.0**attempt))
        error_text = safe_error_message(last_error) if last_error is not None else "unknown error"
        raise FetchError(f"GET failed for {redact_url(url)}: {error_text}")

    def _apply_robots_rate_policy(
        self, url: str, parser: urllib.robotparser.RobotFileParser
    ) -> None:
        host = validate_url_static(url)
        intervals: List[float] = []
        crawl_delay = parser.crawl_delay(USER_AGENT)
        if crawl_delay is not None:
            intervals.append(float(crawl_delay))
        request_rate = parser.request_rate(USER_AGENT)
        if request_rate is not None and request_rate.requests > 0:
            intervals.append(float(request_rate.seconds) / float(request_rate.requests))
        if not intervals:
            return
        required = max(intervals)
        if required > MAX_ROBOTS_INTERVAL_SECONDS:
            raise FetchError(
                f"robots.txt requires a {required:.0f}s request interval; source stopped rather than violating it"
            )
        self.robots_interval_by_host[host] = max(
            self.robots_interval_by_host.get(host, 0.0), required
        )

    def _robots_parser(self, url: str) -> urllib.robotparser.RobotFileParser:
        parsed = urllib.parse.urlsplit(url)
        origin = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))
        if origin in self.robots_cache:
            return self.robots_cache[origin]
        robots_url = origin + "/robots.txt"
        parser = urllib.robotparser.RobotFileParser()
        parser.set_url(robots_url)
        try:
            body = self._raw_get(
                robots_url,
                documented_api=False,
                enforce_redirect_robots=False,
            ).decode("utf-8", errors="replace")
        except FetchError as exc:
            # urllib wraps HTTP status in the message; 404/410 means no robots
            # file, while all ambiguous failures are fail-closed.
            message = str(exc)
            if "HTTP Error 404" in message or "HTTP Error 410" in message:
                parser.parse([])
            else:
                raise FetchError(f"robots.txt unavailable; generic fetch blocked: {exc}") from exc
        else:
            parser.parse(body.splitlines())
        self.robots_cache[origin] = parser
        return parser

    def get(self, url: str, *, documented_api: bool = False) -> bytes:
        if not documented_api:
            self._validate_target(url, documented_api=False)
            parser = self._robots_parser(url)
            if not parser.can_fetch(USER_AGENT, url):
                raise FetchError(f"robots.txt disallows {redact_url(url)}")
            self._apply_robots_rate_policy(url, parser)
        return self._raw_get(url, documented_api=documented_api)


def decode_json(data: bytes, source_url: str) -> Any:
    try:
        return json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ParseError(f"invalid JSON from {redact_url(source_url)}: {exc}") from exc


@dataclass
class CollectionContext:
    fetcher: BaseFetcher
    config_dir: Path
    now: dt.datetime
    defaults: Dict[str, Any]
    mode: str


@dataclass
class SourceResult:
    source_id: str
    provider: str
    success: bool
    complete_snapshot: bool
    authoritative: bool
    jobs: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    error: Optional[str] = None
    requests: List[str] = field(default_factory=list)

    def report(self) -> Dict[str, Any]:
        return {
            "source_id": self.source_id,
            "provider": self.provider,
            "success": self.success,
            "complete_snapshot": self.complete_snapshot,
            "authoritative": self.authoritative,
            "job_count": len(self.jobs),
            "warnings": self.warnings,
            "error": self.error,
            "requests": [redact_url(url) for url in self.requests],
        }


class Adapter:
    provider = "base"
    source_class = ""
    fetched_via = ""
    authoritative = True

    @classmethod
    def plan(cls, source: Dict[str, Any]) -> List[str]:
        raise NotImplementedError

    def collect(self, source: Dict[str, Any], context: CollectionContext) -> SourceResult:
        raise NotImplementedError

    def result(
        self,
        source: Dict[str, Any],
        *,
        jobs: Optional[List[Dict[str, Any]]] = None,
        complete: bool = True,
        warnings: Optional[List[str]] = None,
        requests: Optional[List[str]] = None,
    ) -> SourceResult:
        return SourceResult(
            source_id=source["id"],
            provider=self.provider,
            success=True,
            complete_snapshot=complete,
            authoritative=self.authoritative,
            jobs=jobs or [],
            warnings=warnings or [],
            requests=requests or [],
        )

    def make_job(
        self,
        raw: Dict[str, Any],
        source: Dict[str, Any],
        context: CollectionContext,
        source_url: str,
        extra_flags: Optional[Sequence[str]] = None,
    ) -> Dict[str, Any]:
        return finalize_job(
            raw,
            source=source,
            source_class=self.source_class,
            fetched_via=self.fetched_via,
            source_url=source_url,
            now=context.now,
            defaults=context.defaults,
            extra_flags=extra_flags,
        )


class GreenhouseAdapter(Adapter):
    provider = "greenhouse"
    source_class = "official_ats"
    fetched_via = "documented_public_api"

    @classmethod
    def endpoint(cls, source: Dict[str, Any]) -> str:
        token = urllib.parse.quote(source["board_token"], safe="")
        return f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"

    @classmethod
    def plan(cls, source: Dict[str, Any]) -> List[str]:
        return [cls.endpoint(source)]

    def collect(self, source: Dict[str, Any], context: CollectionContext) -> SourceResult:
        endpoint = self.endpoint(source)
        payload = decode_json(context.fetcher.get(endpoint, documented_api=True), endpoint)
        items = payload.get("jobs") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            raise ParseError("Greenhouse response must contain a jobs array")
        jobs = []
        for item in items:
            if not isinstance(item, dict):
                continue
            departments = item.get("departments") or []
            offices = item.get("offices") or []
            location = item.get("location") or {}
            raw_locations: List[Any] = []
            if isinstance(location, dict) and location.get("name"):
                raw_locations.append(location["name"])
            for office in offices:
                if isinstance(office, dict):
                    raw_locations.append(office.get("location") or office.get("name"))
            jobs.append(
                self.make_job(
                    {
                        "external_id": item.get("id"),
                        "company": source.get("company"),
                        "title": item.get("title"),
                        "description_text": strip_html(item.get("content")),
                        "department": departments[0].get("name") if departments and isinstance(departments[0], dict) else None,
                        "locations": raw_locations,
                        "updated_at": item.get("updated_at"),
                        "expires_at": item.get("application_deadline"),
                        "job_url": item.get("absolute_url"),
                        "apply_url": item.get("absolute_url"),
                        "language": item.get("language"),
                    },
                    source,
                    context,
                    endpoint,
                )
            )
        return self.result(source, jobs=jobs, requests=[endpoint])


class LeverAdapter(Adapter):
    provider = "lever"
    source_class = "official_ats"
    fetched_via = "documented_public_api"

    @classmethod
    def base(cls, source: Dict[str, Any]) -> str:
        host = "api.eu.lever.co" if source.get("region", "global") == "eu" else "api.lever.co"
        site = urllib.parse.quote(source["site"], safe="")
        return f"https://{host}/v0/postings/{site}"

    @classmethod
    def page_url(cls, source: Dict[str, Any], skip: int, limit: int = 100) -> str:
        query = urllib.parse.urlencode({"limit": limit, "mode": "json", "skip": skip})
        return cls.base(source) + "?" + query

    @classmethod
    def plan(cls, source: Dict[str, Any]) -> List[str]:
        return [cls.page_url(source, 0) + " (paginated)"]

    def collect(self, source: Dict[str, Any], context: CollectionContext) -> SourceResult:
        maximum = int(source.get("max_results", 500))
        max_pages = int(source.get("max_pages", DEFAULT_MAX_PAGES))
        items: List[Dict[str, Any]] = []
        requests: List[str] = []
        invalid_items = 0
        page_fingerprints = set()
        offset = 0
        pages = 0
        complete = False
        stalled = False
        while offset < maximum and pages < max_pages:
            limit = min(100, maximum - offset)
            endpoint = self.page_url(source, offset, limit)
            requests.append(endpoint)
            page = decode_json(context.fetcher.get(endpoint, documented_api=True), endpoint)
            if not isinstance(page, list):
                raise ParseError("Lever response must be an array")
            pages += 1
            page_fingerprint = hash_text(
                json.dumps(page, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            )
            if page_fingerprint in page_fingerprints:
                stalled = True
                break
            page_fingerprints.add(page_fingerprint)
            valid = [item for item in page if isinstance(item, dict)]
            invalid_items += len(page) - len(valid)
            items.extend(valid)
            raw_count = len(page)
            offset += raw_count
            if raw_count < limit:
                complete = True
                break
        warnings: List[str] = []
        if invalid_items:
            warnings.append(f"invalid_records_skipped:{invalid_items}")
            complete = False
        if stalled:
            warnings.append("pagination_stalled_repeated_page")
        if pages >= max_pages and not complete:
            warnings.append(f"page_limit_reached:{max_pages}")
        if offset >= maximum and not complete:
            warnings.append(f"truncated_at_max_results:{maximum}")
        jobs = []
        for item in items[:maximum]:
            categories = item.get("categories") or {}
            all_locations = categories.get("allLocations") or [] if isinstance(categories, dict) else []
            if not all_locations and isinstance(categories, dict) and categories.get("location"):
                all_locations = [categories["location"]]
            salary_raw = item.get("salaryRange")
            salary = None
            if isinstance(salary_raw, dict):
                salary = {
                    "min": salary_raw.get("min"),
                    "max": salary_raw.get("max"),
                    "currency": salary_raw.get("currency"),
                    "interval": salary_raw.get("interval"),
                    "text": normalize_space(item.get("salaryDescription")) or None,
                }
            jobs.append(
                self.make_job(
                    {
                        "external_id": item.get("id"),
                        "company": source.get("company"),
                        "title": item.get("text"),
                        "description_text": item.get("descriptionPlain") or strip_html(item.get("description")),
                        "department": categories.get("department") if isinstance(categories, dict) else None,
                        "team": categories.get("team") if isinstance(categories, dict) else None,
                        "seniority": categories.get("level") if isinstance(categories, dict) else None,
                        "employment_type": categories.get("commitment") if isinstance(categories, dict) else None,
                        "workplace_type": item.get("workplaceType") or "unspecified",
                        "locations": [location_from_raw(loc, country=item.get("country")) for loc in all_locations],
                        "salary": salary,
                        "posted_at": item.get("createdAt"),
                        "updated_at": item.get("updatedAt"),
                        "job_url": item.get("hostedUrl"),
                        "apply_url": item.get("applyUrl"),
                    },
                    source,
                    context,
                    requests[-1],
                )
            )
        return self.result(source, jobs=jobs, complete=complete, warnings=warnings, requests=requests)


class AshbyAdapter(Adapter):
    provider = "ashby"
    source_class = "official_ats"
    fetched_via = "documented_public_api"

    @classmethod
    def endpoint(cls, source: Dict[str, Any]) -> str:
        board = urllib.parse.quote(source["board"], safe="")
        include = "true" if source.get("include_compensation", True) else "false"
        return f"https://api.ashbyhq.com/posting-api/job-board/{board}?includeCompensation={include}"

    @classmethod
    def plan(cls, source: Dict[str, Any]) -> List[str]:
        return [cls.endpoint(source)]

    @staticmethod
    def _salary(compensation: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(compensation, dict):
            return None
        summary = compensation.get("scrapeableCompensationSalarySummary") or compensation.get("compensationTierSummary")
        components = compensation.get("summaryComponents") or []
        component = next(
            (
                item
                for item in components
                if isinstance(item, dict) and str(item.get("compensationType", "")).casefold() == "salary"
            ),
            {},
        )
        return {
            "min": component.get("minValue"),
            "max": component.get("maxValue"),
            "currency": component.get("currencyCode"),
            "interval": component.get("interval"),
            "text": normalize_space(summary) or None,
        }

    def collect(self, source: Dict[str, Any], context: CollectionContext) -> SourceResult:
        endpoint = self.endpoint(source)
        payload = decode_json(context.fetcher.get(endpoint, documented_api=True), endpoint)
        items = payload.get("jobs") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            raise ParseError("Ashby response must contain a jobs array")
        jobs = []
        skipped_unlisted = 0
        for item in items:
            if not isinstance(item, dict):
                continue
            if item.get("isListed") is False:
                skipped_unlisted += 1
                continue
            address = item.get("address") or {}
            postal = address.get("postalAddress") or address if isinstance(address, dict) else {}
            locations: List[Any] = [
                location_from_raw(
                    item.get("location"),
                    city=postal.get("addressLocality") if isinstance(postal, dict) else None,
                    region=postal.get("addressRegion") if isinstance(postal, dict) else None,
                    country=postal.get("addressCountry") if isinstance(postal, dict) else None,
                    remote=item.get("isRemote"),
                )
            ]
            for secondary in item.get("secondaryLocations") or []:
                if not isinstance(secondary, dict):
                    continue
                secondary_address = secondary.get("address") or {}
                locations.append(
                    location_from_raw(
                        secondary.get("location"),
                        city=secondary_address.get("addressLocality"),
                        region=secondary_address.get("addressRegion"),
                        country=secondary_address.get("addressCountry"),
                        remote=item.get("isRemote"),
                    )
                )
            jobs.append(
                self.make_job(
                    {
                        "external_id": item.get("id"),
                        "company": source.get("company"),
                        "title": item.get("title"),
                        "description_text": item.get("descriptionPlain") or strip_html(item.get("descriptionHtml")),
                        "department": item.get("department"),
                        "team": item.get("team"),
                        "employment_type": item.get("employmentType"),
                        "workplace_type": item.get("workplaceType"),
                        "locations": locations,
                        "salary": self._salary(item.get("compensation")),
                        "posted_at": item.get("publishedAt"),
                        "job_url": item.get("jobUrl"),
                        "apply_url": item.get("applyUrl"),
                    },
                    source,
                    context,
                    endpoint,
                )
            )
        warnings = [f"unlisted_jobs_skipped:{skipped_unlisted}"] if skipped_unlisted else []
        return self.result(source, jobs=jobs, warnings=warnings, requests=[endpoint])


class SmartRecruitersAdapter(Adapter):
    provider = "smartrecruiters"
    source_class = "official_ats"
    fetched_via = "documented_public_api"

    @classmethod
    def base(cls, source: Dict[str, Any]) -> str:
        identifier = urllib.parse.quote(source["company_identifier"], safe="")
        return f"https://api.smartrecruiters.com/v1/companies/{identifier}/postings"

    @classmethod
    def list_url(cls, source: Dict[str, Any], offset: int, limit: int) -> str:
        return cls.base(source) + "?" + urllib.parse.urlencode({"limit": limit, "offset": offset})

    @classmethod
    def detail_url(cls, source: Dict[str, Any], posting_id: Any) -> str:
        return cls.base(source) + "/" + urllib.parse.quote(str(posting_id), safe="")

    @classmethod
    def plan(cls, source: Dict[str, Any]) -> List[str]:
        return [cls.list_url(source, 0, 100) + " (paginated + public detail GET per posting)"]

    @staticmethod
    def _label(value: Any) -> Any:
        return value.get("label") if isinstance(value, dict) else value

    @staticmethod
    def _description(item: Dict[str, Any]) -> str:
        sections = ((item.get("jobAd") or {}).get("sections") or {})
        if not isinstance(sections, dict):
            return ""
        parts = []
        for key in ("companyDescription", "jobDescription", "qualifications", "additionalInformation"):
            section = sections.get(key)
            if isinstance(section, dict) and section.get("text"):
                parts.append(strip_html(section["text"]))
        return normalize_space(" ".join(parts))

    def _make(self, item: Dict[str, Any], source: Dict[str, Any], context: CollectionContext, endpoint: str) -> Dict[str, Any]:
        company_obj = item.get("company") or {}
        location = item.get("location") or {}
        employment = item.get("typeOfEmployment") or item.get("employmentType")
        return self.make_job(
            {
                "external_id": item.get("id") or item.get("uuid"),
                "company": company_obj.get("name") if isinstance(company_obj, dict) else source.get("company"),
                "title": item.get("name") or item.get("title"),
                "description_text": self._description(item) or item.get("description"),
                "department": self._label(item.get("department")),
                "seniority": self._label(item.get("experienceLevel")),
                "employment_type": self._label(employment),
                "workplace_type": "remote" if isinstance(location, dict) and location.get("remote") is True else None,
                "locations": [
                    location_from_raw(
                        ", ".join(
                            normalize_space(location.get(part))
                            for part in ("city", "region", "country")
                            if normalize_space(location.get(part))
                        ),
                        city=location.get("city"),
                        region=location.get("region"),
                        country=location.get("country"),
                        remote=location.get("remote"),
                    )
                ] if isinstance(location, dict) else [],
                "posted_at": item.get("releasedDate") or item.get("createdOn"),
                "updated_at": item.get("updatedOn"),
                "job_url": item.get("applyUrl") or item.get("ref"),
                "apply_url": item.get("applyUrl"),
                "language": item.get("language"),
            },
            source,
            context,
            endpoint,
        )

    def collect(self, source: Dict[str, Any], context: CollectionContext) -> SourceResult:
        maximum = int(source.get("max_results", 300))
        max_pages = int(source.get("max_pages", DEFAULT_MAX_PAGES))
        summaries: List[Dict[str, Any]] = []
        requests: List[str] = []
        total_found: Optional[int] = None
        offset = 0
        pages = 0
        invalid_summaries = 0
        page_fingerprints = set()
        stalled = False
        transport_complete = False
        while offset < maximum and pages < max_pages:
            limit = min(100, maximum - offset)
            endpoint = self.list_url(source, offset, limit)
            requests.append(endpoint)
            payload = decode_json(context.fetcher.get(endpoint, documented_api=True), endpoint)
            if not isinstance(payload, dict) or not isinstance(payload.get("content"), list):
                raise ParseError("SmartRecruiters response must contain a content array")
            raw_page = payload["content"]
            pages += 1
            page_fingerprint = hash_text(
                json.dumps(raw_page, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            )
            if page_fingerprint in page_fingerprints:
                stalled = True
                break
            page_fingerprints.add(page_fingerprint)
            page = [item for item in raw_page if isinstance(item, dict)]
            invalid_summaries += len(raw_page) - len(page)
            summaries.extend(page)
            raw_count = len(raw_page)
            offset += raw_count
            if total_found is None:
                try:
                    total_found = int(payload.get("totalFound"))
                except (TypeError, ValueError):
                    total_found = None
            if raw_count < limit or (total_found is not None and offset >= total_found):
                transport_complete = True
                break
        complete = transport_complete and invalid_summaries == 0
        warnings: List[str] = []
        if invalid_summaries:
            warnings.append(f"invalid_records_skipped:{invalid_summaries}")
        if stalled:
            warnings.append("pagination_stalled_repeated_page")
        if pages >= max_pages and not transport_complete:
            warnings.append(f"page_limit_reached:{max_pages}")
        if offset >= maximum and not transport_complete:
            warnings.append(f"truncated_at_max_results:{maximum}")
        jobs: List[Dict[str, Any]] = []
        detail_failures = 0
        for summary in summaries[:maximum]:
            posting_id = summary.get("id") or summary.get("uuid")
            if posting_id is None:
                detail_failures += 1
                jobs.append(self._make(summary, source, context, requests[-1]))
                continue
            detail_endpoint = self.detail_url(source, posting_id)
            requests.append(detail_endpoint)
            try:
                detail = decode_json(context.fetcher.get(detail_endpoint, documented_api=True), detail_endpoint)
                if not isinstance(detail, dict):
                    raise ParseError("SmartRecruiters detail response must be an object")
            except (FetchError, ParseError):
                detail_failures += 1
                jobs.append(self._make(summary, source, context, requests[-2]))
                continue
            jobs.append(self._make(detail, source, context, detail_endpoint))
        if detail_failures:
            warnings.append(f"detail_failures:{detail_failures}")
            complete = False
        return self.result(source, jobs=jobs, complete=complete, warnings=warnings, requests=requests)


class _JsonLdExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_jsonld = False
        self.buffer: List[str] = []
        self.blocks: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        if tag.casefold() != "script":
            return
        attributes = {key.casefold(): (value or "") for key, value in attrs}
        if attributes.get("type", "").split(";", 1)[0].strip().casefold() == "application/ld+json":
            self.in_jsonld = True
            self.buffer = []

    def handle_data(self, data: str) -> None:
        if self.in_jsonld:
            self.buffer.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() == "script" and self.in_jsonld:
            self.blocks.append("".join(self.buffer))
            self.in_jsonld = False
            self.buffer = []


def _walk_jsonld(value: Any) -> Iterable[Dict[str, Any]]:
    if isinstance(value, dict):
        type_value = value.get("@type")
        types = type_value if isinstance(type_value, list) else [type_value]
        if any(str(item).casefold() == "jobposting" for item in types if item is not None):
            yield value
        for child in value.values():
            yield from _walk_jsonld(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_jsonld(child)


def _jsonld_salary(value: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(value, dict):
        return None
    currency = value.get("currency")
    amount = value.get("value")
    if isinstance(amount, dict):
        minimum = amount.get("minValue")
        maximum = amount.get("maxValue")
        if minimum is None and maximum is None:
            minimum = maximum = amount.get("value")
        interval = amount.get("unitText")
    else:
        minimum = maximum = amount
        interval = None
    return {
        "min": minimum,
        "max": maximum,
        "currency": currency,
        "interval": interval,
        "text": None,
    }


def _jsonld_locations(value: Any, remote: bool) -> List[Dict[str, Any]]:
    if value is None:
        return [location_from_raw("Remote", remote=True)] if remote else []
    items = value if isinstance(value, list) else [value]
    output = []
    for item in items:
        if not isinstance(item, dict):
            output.append(location_from_raw(item, remote=remote))
            continue
        address = item.get("address") or {}
        if isinstance(address, str):
            output.append(location_from_raw(address, remote=remote))
            continue
        city = address.get("addressLocality") if isinstance(address, dict) else None
        region = address.get("addressRegion") if isinstance(address, dict) else None
        country_value = address.get("addressCountry") if isinstance(address, dict) else None
        if isinstance(country_value, dict):
            country_value = country_value.get("name")
        raw = ", ".join(
            normalize_space(part) for part in (city, region, country_value) if normalize_space(part)
        )
        output.append(location_from_raw(raw or item.get("name"), city=city, region=region, country=country_value, remote=remote))
    return output


class JsonLdAdapter(Adapter):
    provider = "jsonld"
    source_class = "company_site"
    fetched_via = "public_jsonld_with_robots"

    @classmethod
    def plan(cls, source: Dict[str, Any]) -> List[str]:
        return list(source["urls"])

    @classmethod
    def parse_page(
        cls,
        data: bytes,
        page_url: str,
        source: Dict[str, Any],
        context: CollectionContext,
        fetched_via: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], List[str]]:
        parser = _JsonLdExtractor()
        parser.feed(data.decode("utf-8", errors="replace"))
        parser.close()
        warnings: List[str] = []
        objects: List[Dict[str, Any]] = []
        for block in parser.blocks:
            try:
                payload = json.loads(block.strip())
            except json.JSONDecodeError:
                warnings.append(f"invalid_jsonld:{redact_url(page_url)}")
                continue
            objects.extend(_walk_jsonld(payload))
        jobs = []
        for item in objects:
            organization = item.get("hiringOrganization") or {}
            identifier = item.get("identifier")
            if isinstance(identifier, dict):
                identifier = identifier.get("value") or identifier.get("name")
            remote = str(item.get("jobLocationType", "")).casefold() in {
                "telecommute",
                "remote",
            }
            employment = item.get("employmentType")
            if isinstance(employment, list):
                employment = ", ".join(normalize_space(value) for value in employment)
            job_url = urllib.parse.urljoin(page_url, normalize_space(item.get("url")) or page_url)
            raw = {
                "external_id": identifier,
                "company": organization.get("name") if isinstance(organization, dict) else source.get("company"),
                "title": item.get("title"),
                "description_text": strip_html(item.get("description")),
                "employment_type": employment,
                "workplace_type": "remote" if remote else None,
                "locations": _jsonld_locations(item.get("jobLocation"), remote),
                "salary": _jsonld_salary(item.get("baseSalary")),
                "posted_at": item.get("datePosted"),
                "updated_at": item.get("dateModified"),
                "expires_at": item.get("validThrough"),
                "job_url": job_url,
                "apply_url": job_url,
                "language": item.get("inLanguage"),
            }
            adapter = cls()
            if fetched_via:
                adapter.fetched_via = fetched_via
            jobs.append(adapter.make_job(raw, source, context, page_url))
        if not objects:
            warnings.append(f"no_jobposting_jsonld:{redact_url(page_url)}")
        return jobs, warnings

    def collect(self, source: Dict[str, Any], context: CollectionContext) -> SourceResult:
        jobs: List[Dict[str, Any]] = []
        warnings: List[str] = []
        requests: List[str] = []
        complete = True
        for page_url in source["urls"]:
            requests.append(page_url)
            try:
                data = context.fetcher.get(page_url, documented_api=False)
                parsed, page_warnings = self.parse_page(data, page_url, source, context)
                jobs.extend(parsed)
                warnings.extend(page_warnings)
                if page_warnings:
                    complete = False
            except Exception as exc:
                complete = False
                warnings.append(
                    f"page_failed:{redact_url(page_url)}:{type(exc).__name__}:{safe_error_message(exc)}"
                )
        return self.result(source, jobs=jobs, complete=complete, warnings=warnings, requests=requests)


def _xml_local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].casefold()


def _sitemap_entries(data: bytes) -> Tuple[str, List[Tuple[str, Optional[str]]]]:
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise ParseError(f"invalid sitemap XML: {exc}") from exc
    root_type = _xml_local_name(root.tag)
    if root_type not in {"urlset", "sitemapindex"}:
        raise ParseError(f"unsupported sitemap root: {root_type}")
    entries = []
    child_name = "url" if root_type == "urlset" else "sitemap"
    for child in root:
        if _xml_local_name(child.tag) != child_name:
            continue
        location = None
        last_modified = None
        for field_node in child:
            name = _xml_local_name(field_node.tag)
            if name == "loc":
                location = normalize_space(field_node.text)
            elif name == "lastmod":
                last_modified = normalize_space(field_node.text) or None
        if location:
            entries.append((location, last_modified))
    return root_type, entries


class SitemapJsonLdAdapter(Adapter):
    provider = "sitemap_jsonld"
    source_class = "company_site"
    fetched_via = "public_sitemap_and_jsonld_with_robots"

    @classmethod
    def plan(cls, source: Dict[str, Any]) -> List[str]:
        return [source["sitemap_url"] + " (one-level sitemap index + filtered JobPosting pages)"]

    def collect(self, source: Dict[str, Any], context: CollectionContext) -> SourceResult:
        root_url = source["sitemap_url"]
        root_host = urllib.parse.urlsplit(root_url).hostname
        include = re.compile(source["include_regex"])
        max_urls = int(source.get("max_urls", 200))
        max_sitemaps = int(source.get("max_sitemaps", 20))
        requests = [root_url]
        warnings: List[str] = []
        complete = True
        root_type, entries = _sitemap_entries(context.fetcher.get(root_url, documented_api=False))
        page_entries: List[Tuple[str, Optional[str]]] = []
        if root_type == "sitemapindex":
            if len(entries) > max_sitemaps:
                entries = entries[:max_sitemaps]
                warnings.append(f"sitemap_index_truncated:{max_sitemaps}")
                complete = False
            for child_url, _ in entries:
                if urllib.parse.urlsplit(child_url).hostname != root_host:
                    warnings.append(f"cross_host_sitemap_skipped:{redact_url(child_url)}")
                    complete = False
                    continue
                requests.append(child_url)
                try:
                    child_type, child_entries = _sitemap_entries(
                        context.fetcher.get(child_url, documented_api=False)
                    )
                    if child_type != "urlset":
                        warnings.append(f"nested_sitemap_index_skipped:{redact_url(child_url)}")
                        complete = False
                        continue
                    page_entries.extend(child_entries)
                except Exception as exc:
                    warnings.append(
                        f"child_sitemap_failed:{redact_url(child_url)}:{type(exc).__name__}:{safe_error_message(exc)}"
                    )
                    complete = False
        else:
            page_entries = entries
        candidates = []
        for url, lastmod in page_entries:
            if urllib.parse.urlsplit(url).hostname != root_host:
                warnings.append(f"cross_host_job_url_skipped:{redact_url(url)}")
                complete = False
                continue
            if include.search(url):
                candidates.append((url, lastmod))
        if len(candidates) > max_urls:
            candidates = candidates[:max_urls]
            warnings.append(f"job_urls_truncated:{max_urls}")
            complete = False
        jobs: List[Dict[str, Any]] = []
        for page_url, lastmod in candidates:
            requests.append(page_url)
            try:
                parsed, page_warnings = JsonLdAdapter.parse_page(
                    context.fetcher.get(page_url, documented_api=False),
                    page_url,
                    source,
                    context,
                    fetched_via=self.fetched_via,
                )
                if lastmod:
                    for job in parsed:
                        if not job.get("updated_at"):
                            job["updated_at"] = lastmod
                            _recompute_merged(job, context.now, context.defaults)
                jobs.extend(parsed)
                warnings.extend(page_warnings)
                if page_warnings:
                    complete = False
            except Exception as exc:
                warnings.append(
                    f"page_failed:{redact_url(page_url)}:{type(exc).__name__}:{safe_error_message(exc)}"
                )
                complete = False
        return self.result(source, jobs=jobs, complete=complete, warnings=warnings, requests=requests)


class GoogleCseAdapter(Adapter):
    provider = "google_cse"
    source_class = "search_api"
    fetched_via = "documented_search_api"
    authoritative = False

    @classmethod
    def endpoint(
        cls, source: Dict[str, Any], *, key: str, cx: str, start: int, number: int
    ) -> str:
        params: Dict[str, Any] = {
            "cx": cx,
            "key": key,
            "num": number,
            "q": source["query"],
            "start": start,
        }
        if source.get("site_search"):
            params["siteSearch"] = source["site_search"]
        return "https://customsearch.googleapis.com/customsearch/v1?" + urllib.parse.urlencode(params)

    @classmethod
    def plan(cls, source: Dict[str, Any]) -> List[str]:
        key = f"<env:{source['api_key_env']}>"
        cx = f"<env:{source['cx_env']}>"
        return [redact_url(cls.endpoint(source, key=key, cx=cx, start=1, number=10)) + " (paginated)"]

    def collect(self, source: Dict[str, Any], context: CollectionContext) -> SourceResult:
        if context.mode == "fixtures":
            key, cx = "fixture-key", "fixture-cx"
        else:
            key = os.environ.get(source["api_key_env"], "")
            cx = os.environ.get(source["cx_env"], "")
            if not key or not cx:
                raise ConfigError(
                    f"Google CSE credentials missing in {source['api_key_env']} / {source['cx_env']}"
                )
        maximum = min(100, int(source.get("max_results", 20)))
        requests: List[str] = []
        jobs: List[Dict[str, Any]] = []
        warnings: List[str] = []
        blocked_results = 0
        start = 1
        seen_starts = set()
        pages = 0
        while len(jobs) < maximum and start <= 91 and pages < 10:
            if start in seen_starts:
                warnings.append("pagination_stalled_repeated_cursor")
                break
            seen_starts.add(start)
            pages += 1
            number = min(10, maximum - len(jobs))
            endpoint = self.endpoint(source, key=key, cx=cx, start=start, number=number)
            requests.append(redact_url(endpoint))
            payload = decode_json(context.fetcher.get(endpoint, documented_api=True), endpoint)
            if not isinstance(payload, dict):
                raise ParseError("Google CSE response must be an object")
            items = payload.get("items") or []
            if not isinstance(items, list):
                raise ParseError("Google CSE items must be an array")
            for item in items:
                if not isinstance(item, dict) or not item.get("link"):
                    continue
                link = item["link"]
                try:
                    validate_url_static(link)
                except ConfigError:
                    blocked_results += 1
                    continue
                jobs.append(
                    self.make_job(
                        {
                            "external_id": item.get("cacheId"),
                            "company": source.get("company") or item.get("displayLink"),
                            "title": item.get("title"),
                            "description_text": item.get("snippet"),
                            "job_url": link,
                            "apply_url": link,
                        },
                        source,
                        context,
                        requests[-1],
                        extra_flags=["discovery_only", "description_is_search_snippet"],
                    )
                )
            if not items:
                break
            next_pages = (payload.get("queries") or {}).get("nextPage") or []
            if not next_pages:
                break
            try:
                next_start = int(next_pages[0]["startIndex"])
            except (KeyError, IndexError, TypeError, ValueError):
                break
            if next_start <= start or next_start > 91:
                warnings.append("pagination_stalled_invalid_cursor")
                break
            start = next_start
        if blocked_results:
            warnings.append(f"restricted_or_unsafe_results_skipped:{blocked_results}")
        return self.result(
            source,
            jobs=jobs[:maximum],
            complete=False,
            warnings=warnings
            + [
                "search_results_are_discovery_only",
                "google_cse_existing_customers_only_shutdown_2027-01-01",
            ],
            requests=requests,
        )


class ManualImportAdapter(Adapter):
    provider = "manual_import"
    source_class = "user_supplied"
    fetched_via = "user_authorized_local_import"
    authoritative = False

    @classmethod
    def plan(cls, source: Dict[str, Any]) -> List[str]:
        return [f"local import: {source['path']}"]

    @staticmethod
    def _records(
        path: Path, format_name: str, max_response_bytes: int
    ) -> List[Dict[str, Any]]:
        try:
            with path.open("rb") as handle:
                data = handle.read(max_response_bytes + 1)
            if len(data) > max_response_bytes:
                raise ConfigError(
                    f"manual import exceeds {max_response_bytes} bytes"
                )
            text = data.decode("utf-8-sig")
            if format_name == "csv":
                return [dict(row) for row in csv.DictReader(io.StringIO(text, newline=""))]
            if format_name == "jsonl":
                records = []
                for line_number, line in enumerate(text.splitlines(), 1):
                    if not line.strip():
                        continue
                    value = json.loads(line)
                    if not isinstance(value, dict):
                        raise ConfigError(f"JSONL line {line_number} is not an object")
                    records.append(value)
                return records
            payload = json.loads(text)
        except ConfigError:
            raise
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ConfigError(
                f"cannot read authorized import ({type(exc).__name__})"
            ) from exc
        if isinstance(payload, dict):
            payload = payload.get("jobs")
        if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
            raise ConfigError("JSON import must be an array of objects or an object with a jobs array")
        return payload

    def collect(self, source: Dict[str, Any], context: CollectionContext) -> SourceResult:
        configured_path = Path(source["path"])
        if configured_path.is_absolute():
            raise ConfigError("manual import path must be relative to the config directory")
        config_root = context.config_dir.resolve()
        path = (config_root / configured_path).resolve()
        try:
            path.relative_to(config_root)
        except ValueError as exc:
            raise ConfigError("manual import path escapes the config directory") from exc
        if not path.is_file():
            raise ConfigError("manual import must be a regular file inside the config directory")
        format_name = source.get("format") or path.suffix.lstrip(".").casefold()
        if format_name == "ndjson":
            format_name = "jsonl"
        records = self._records(path, format_name, int(context.defaults["max_response_bytes"]))
        jobs = []
        for item in records:
            locations = item.get("locations")
            if not locations and item.get("location"):
                locations = [piece.strip() for piece in str(item["location"]).split(";") if piece.strip()]
            source_url = normalize_space(item.get("source_url") or item.get("job_url")) or "user-provided-local-import"
            jobs.append(
                self.make_job(
                    {
                        "external_id": item.get("external_id") or item.get("id"),
                        "company": item.get("company") or source.get("company"),
                        "title": item.get("title"),
                        "description_text": item.get("description_text") or item.get("description"),
                        "department": item.get("department"),
                        "team": item.get("team"),
                        "seniority": item.get("seniority"),
                        "employment_type": item.get("employment_type"),
                        "workplace_type": item.get("workplace_type"),
                        "locations": locations,
                        "salary": item.get("salary"),
                        "posted_at": item.get("posted_at"),
                        "updated_at": item.get("updated_at"),
                        "expires_at": item.get("expires_at"),
                        "job_url": item.get("job_url"),
                        "apply_url": item.get("apply_url"),
                        "language": item.get("language"),
                    },
                    source,
                    context,
                    source_url,
                    extra_flags=["user_supplied_not_live_verified"],
                )
            )
        return self.result(
            source,
            jobs=jobs,
            complete=False,
            warnings=["manual_import_is_not_a_live_complete_snapshot"],
            requests=["local import"],
        )


ADAPTERS = {
    "greenhouse": GreenhouseAdapter,
    "lever": LeverAdapter,
    "ashby": AshbyAdapter,
    "smartrecruiters": SmartRecruitersAdapter,
    "jsonld": JsonLdAdapter,
    "sitemap_jsonld": SitemapJsonLdAdapter,
    "google_cse": GoogleCseAdapter,
    "manual_import": ManualImportAdapter,
}


def _validate_sensitive_keys(value: Any, path: str = "config") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).casefold() in SENSITIVE_CONFIG_KEYS:
                raise ConfigError(
                    f"sensitive credential field {path}.{key} is forbidden; only named environment variables are supported"
                )
            _validate_sensitive_keys(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _validate_sensitive_keys(child, f"{path}[{index}]")


def _positive_number(value: Any, name: str, *, minimum: float, maximum: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{name} must be numeric") from exc
    if not minimum <= number <= maximum:
        raise ConfigError(f"{name} must be between {minimum} and {maximum}")
    return number


def load_config(path: Path) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"cannot read config {path}: {exc}") from exc
    if not isinstance(config, dict):
        raise ConfigError("config root must be an object")
    _validate_sensitive_keys(config)
    if str(config.get("schema_version", "1")) != "1":
        raise ConfigError("config schema_version must be '1'")
    defaults = dict(DEFAULTS)
    supplied_defaults = config.get("defaults") or {}
    if not isinstance(supplied_defaults, dict):
        raise ConfigError("defaults must be an object")
    defaults.update(supplied_defaults)
    defaults["fresh_days"] = int(_positive_number(defaults["fresh_days"], "fresh_days", minimum=0, maximum=3650))
    defaults["stale_days"] = int(_positive_number(defaults["stale_days"], "stale_days", minimum=1, maximum=3650))
    if defaults["stale_days"] < defaults["fresh_days"]:
        raise ConfigError("stale_days must be >= fresh_days")
    defaults["close_after_misses"] = int(_positive_number(defaults["close_after_misses"], "close_after_misses", minimum=1, maximum=10))
    defaults["request_interval_seconds"] = _positive_number(defaults["request_interval_seconds"], "request_interval_seconds", minimum=0.2, maximum=60)
    defaults["timeout_seconds"] = _positive_number(defaults["timeout_seconds"], "timeout_seconds", minimum=1, maximum=60)
    defaults["max_response_bytes"] = int(_positive_number(defaults["max_response_bytes"], "max_response_bytes", minimum=1024, maximum=64 * 1024 * 1024))
    defaults["max_retries"] = int(_positive_number(defaults["max_retries"], "max_retries", minimum=0, maximum=5))
    sources = config.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ConfigError("sources must be a non-empty array")
    seen_ids = set()
    for index, source in enumerate(sources):
        if not isinstance(source, dict):
            raise ConfigError(f"sources[{index}] must be an object")
        if source.get("enabled", True) is False:
            continue
        source_id = source.get("id")
        if not isinstance(source_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,80}", source_id):
            raise ConfigError(f"sources[{index}].id is invalid")
        if source_id in seen_ids:
            raise ConfigError(f"duplicate source id: {source_id}")
        seen_ids.add(source_id)
        provider = source.get("provider")
        if provider not in PROVIDER_REQUIREMENTS:
            raise ConfigError(f"unsupported provider for {source_id}: {provider!r}")
        for key in PROVIDER_REQUIREMENTS[provider]:
            if source.get(key) in (None, "", []):
                raise ConfigError(f"source {source_id} requires {key}")
        if provider in {"greenhouse", "lever", "ashby", "smartrecruiters"}:
            identifier_key = {
                "greenhouse": "board_token",
                "lever": "site",
                "ashby": "board",
                "smartrecruiters": "company_identifier",
            }[provider]
            if not re.fullmatch(r"[A-Za-z0-9._-]+", str(source[identifier_key])):
                raise ConfigError(f"source {source_id} has unsafe {identifier_key}")
        if provider == "lever" and source.get("region", "global") not in {"global", "eu"}:
            raise ConfigError(f"source {source_id} region must be global or eu")
        if provider in {"lever", "smartrecruiters"}:
            _positive_number(source.get("max_results", 500), f"{source_id}.max_results", minimum=1, maximum=5000)
            _positive_number(
                source.get("max_pages", DEFAULT_MAX_PAGES),
                f"{source_id}.max_pages",
                minimum=1,
                maximum=100,
            )
        if provider == "jsonld":
            if not isinstance(source["urls"], list) or not all(isinstance(url, str) for url in source["urls"]):
                raise ConfigError(f"source {source_id}.urls must be an array of URLs")
            for url in source["urls"]:
                validate_url_static(url)
        if provider == "sitemap_jsonld":
            validate_url_static(source["sitemap_url"])
            try:
                re.compile(source["include_regex"])
            except re.error as exc:
                raise ConfigError(f"source {source_id} include_regex is invalid: {exc}") from exc
            _positive_number(source.get("max_urls", 200), f"{source_id}.max_urls", minimum=1, maximum=2000)
            _positive_number(source.get("max_sitemaps", 20), f"{source_id}.max_sitemaps", minimum=1, maximum=100)
        if provider == "google_cse":
            for key, allowed_name in GOOGLE_CSE_ENV_VARS.items():
                if source[key] != allowed_name:
                    raise ConfigError(
                        f"source {source_id}.{key} must be {allowed_name}; arbitrary environment variables are forbidden"
                    )
            _positive_number(source.get("max_results", 20), f"{source_id}.max_results", minimum=1, maximum=100)
        if provider == "manual_import":
            if not isinstance(source["path"], str):
                raise ConfigError(f"source {source_id} path must be a string")
            if Path(source["path"]).is_absolute():
                raise ConfigError(
                    f"source {source_id} path must be relative to the config directory"
                )
            inferred = source.get("format") or Path(source["path"]).suffix.lstrip(".").casefold()
            if inferred == "ndjson":
                inferred = "jsonl"
            if inferred not in {"json", "jsonl", "csv"}:
                raise ConfigError(f"source {source_id} format must be json, jsonl, or csv")
    filters = config.get("filters") or {}
    if not isinstance(filters, dict):
        raise ConfigError("filters must be an object")
    for list_key in ("title_include", "title_exclude", "keywords_any", "location_include"):
        if list_key in filters and (
            not isinstance(filters[list_key], list)
            or not all(isinstance(item, str) for item in filters[list_key])
        ):
            raise ConfigError(f"filters.{list_key} must be an array of strings")
    if "posted_within_days" in filters:
        _positive_number(filters["posted_within_days"], "filters.posted_within_days", minimum=0, maximum=3650)
    if "min_quality_score" in filters:
        _positive_number(filters["min_quality_score"], "filters.min_quality_score", minimum=0, maximum=100)
    return config, defaults


def job_matches_filters(
    job: Dict[str, Any], filters: Dict[str, Any], now: dt.datetime
) -> bool:
    title = _hash_norm(job.get("title"))
    includes = [_hash_norm(value) for value in filters.get("title_include", []) if _hash_norm(value)]
    excludes = [_hash_norm(value) for value in filters.get("title_exclude", []) if _hash_norm(value)]
    if includes and not any(value in title for value in includes):
        return False
    if excludes and any(value in title for value in excludes):
        return False
    haystack = _hash_norm(
        " ".join(
            str(job.get(field_name) or "")
            for field_name in ("title", "description_text", "department", "team")
        )
    )
    keywords = [_hash_norm(value) for value in filters.get("keywords_any", []) if _hash_norm(value)]
    if keywords and not any(value in haystack for value in keywords):
        return False
    location_text = _hash_norm(
        " ".join(
            " ".join(str(loc.get(field_name) or "") for field_name in ("raw", "city", "region", "country"))
            for loc in job.get("locations", [])
        )
    )
    location_needles = [_hash_norm(value) for value in filters.get("location_include", []) if _hash_norm(value)]
    if location_needles and not any(value in location_text for value in location_needles):
        return False
    if filters.get("remote_only"):
        remote = job.get("workplace_type") == "remote" or any(loc.get("remote") for loc in job.get("locations", []))
        if not remote:
            return False
    if "posted_within_days" in filters:
        reference = parse_datetime(job.get("posted_at")) or parse_datetime(job.get("updated_at"))
        if reference is None:
            if not filters.get("allow_unknown_dates", True):
                return False
        elif (now - reference).total_seconds() / 86400 > float(filters["posted_within_days"]):
            return False
    if job.get("quality_score", 0) < int(filters.get("min_quality_score", 0)):
        return False
    return True


def job_identity_aliases(job: Dict[str, Any]) -> List[str]:
    """Return bounded, non-secret aliases used to keep a merged UID stable."""
    aliases = set()

    def add(kind: str, value: Any) -> None:
        normalized = normalize_space(value)
        if normalized:
            aliases.add(f"{kind}:{hash_text(normalized)}")

    add("url", job.get("canonical_url"))
    for provenance in job.get("provenance", []):
        if not isinstance(provenance, dict):
            continue
        add("url", provenance.get("job_canonical_url"))
        source_id = normalize_space(provenance.get("source_id"))
        external_id = normalize_space(provenance.get("external_id"))
        if source_id and external_id:
            add("external", f"{source_id}\0{external_id}")
    return sorted(aliases)


class StateStore:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(str(path))
        self.connection.row_factory = sqlite3.Row
        self._init_schema()

    def close(self) -> None:
        self.connection.close()

    def _init_schema(self) -> None:
        self.connection.executescript(
            """
            PRAGMA foreign_keys = ON;
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                mode TEXT NOT NULL,
                source_count INTEGER NOT NULL,
                success_count INTEGER NOT NULL DEFAULT 0,
                error_count INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS jobs (
                job_uid TEXT PRIMARY KEY,
                canonical_url TEXT,
                content_fingerprint TEXT NOT NULL,
                job_json TEXT NOT NULL,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                last_changed TEXT NOT NULL,
                status TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS source_jobs (
                source_id TEXT NOT NULL,
                job_uid TEXT NOT NULL,
                authoritative INTEGER NOT NULL,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                missed_successful_snapshots INTEGER NOT NULL DEFAULT 0,
                active INTEGER NOT NULL DEFAULT 1,
                PRIMARY KEY (source_id, job_uid),
                FOREIGN KEY (job_uid) REFERENCES jobs(job_uid)
            );
            CREATE TABLE IF NOT EXISTS source_runs (
                run_id TEXT NOT NULL,
                source_id TEXT NOT NULL,
                provider TEXT NOT NULL,
                success INTEGER NOT NULL,
                complete_snapshot INTEGER NOT NULL,
                error TEXT,
                PRIMARY KEY (run_id, source_id),
                FOREIGN KEY (run_id) REFERENCES runs(run_id)
            );
            CREATE TABLE IF NOT EXISTS observations (
                run_id TEXT NOT NULL,
                source_id TEXT NOT NULL,
                job_uid TEXT NOT NULL,
                observed_at TEXT NOT NULL,
                source_url TEXT,
                PRIMARY KEY (run_id, source_id, job_uid),
                FOREIGN KEY (run_id) REFERENCES runs(run_id),
                FOREIGN KEY (job_uid) REFERENCES jobs(job_uid)
            );
            CREATE TABLE IF NOT EXISTS job_aliases (
                alias_key TEXT PRIMARY KEY,
                job_uid TEXT NOT NULL,
                FOREIGN KEY (job_uid) REFERENCES jobs(job_uid)
            );
            CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
            CREATE INDEX IF NOT EXISTS idx_source_jobs_active ON source_jobs(source_id, active);
            CREATE INDEX IF NOT EXISTS idx_job_aliases_uid ON job_aliases(job_uid);
            """
        )
        # Backfill deterministic aliases when opening a state database created
        # by an earlier version of the collector.
        for row in self.connection.execute("SELECT job_uid, job_json FROM jobs").fetchall():
            try:
                job = json.loads(row["job_json"])
            except (TypeError, json.JSONDecodeError):
                continue
            for alias in job_identity_aliases(job):
                self.connection.execute(
                    "INSERT OR IGNORE INTO job_aliases(alias_key, job_uid) VALUES (?, ?)",
                    (alias, row["job_uid"]),
                )
        self.connection.commit()

    def _resolve_job_uid(self, job: Dict[str, Any]) -> Tuple[str, List[str]]:
        aliases = job_identity_aliases(job)
        candidate_uids: List[str] = []
        if aliases:
            placeholders = ",".join("?" for _ in aliases)
            rows = self.connection.execute(
                f"SELECT DISTINCT job_uid FROM job_aliases WHERE alias_key IN ({placeholders})",
                aliases,
            ).fetchall()
            candidate_uids.extend(row["job_uid"] for row in rows)
        if not candidate_uids:
            canonical = job.get("canonical_url")
            row = self.connection.execute(
                """
                SELECT job_uid FROM jobs
                WHERE (? != '' AND canonical_url = ?)
                ORDER BY first_seen ASC, job_uid ASC
                LIMIT 1
                """,
                (canonical or "", canonical or ""),
            ).fetchone()
            if row is not None:
                candidate_uids.append(row["job_uid"])
        resolved = job.get("job_uid") or ""
        if candidate_uids:
            placeholders = ",".join("?" for _ in candidate_uids)
            row = self.connection.execute(
                f"SELECT job_uid FROM jobs WHERE job_uid IN ({placeholders}) ORDER BY first_seen ASC, job_uid ASC LIMIT 1",
                candidate_uids,
            ).fetchone()
            if row is not None:
                resolved = row["job_uid"]
        job["job_uid"] = resolved
        return resolved, aliases

    def update(
        self,
        run_id: str,
        started_at: str,
        mode: str,
        results: Sequence[SourceResult],
        jobs: Sequence[Dict[str, Any]],
        close_after_misses: int,
    ) -> Dict[str, Any]:
        timestamp = isoformat(utc_now())
        counts = {"new": 0, "changed": 0, "unchanged": 0, "closed": 0, "reopened": 0}
        before_status: Dict[str, str] = {}
        authoritative_by_source = {result.source_id: result.authoritative for result in results}
        with self.connection:
            self.connection.execute(
                "INSERT INTO runs(run_id, started_at, mode, source_count) VALUES (?, ?, ?, ?)",
                (run_id, started_at, mode, len(results)),
            )
            for result in results:
                self.connection.execute(
                    "INSERT INTO source_runs(run_id, source_id, provider, success, complete_snapshot, error) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        run_id,
                        result.source_id,
                        result.provider,
                        int(result.success),
                        int(result.complete_snapshot),
                        result.error,
                    ),
                )
            seen_by_source: Dict[str, set] = {result.source_id: set() for result in results}
            for job in jobs:
                uid, aliases = self._resolve_job_uid(job)
                prior = self.connection.execute(
                    "SELECT content_fingerprint, status, first_seen FROM jobs WHERE job_uid = ?",
                    (uid,),
                ).fetchone()
                before_status[uid] = prior["status"] if prior else ""
                if prior is None:
                    counts["new"] += 1
                    first_seen = timestamp
                    last_changed = timestamp
                elif prior["content_fingerprint"] != job["content_fingerprint"]:
                    counts["changed"] += 1
                    first_seen = prior["first_seen"]
                    last_changed = timestamp
                else:
                    counts["unchanged"] += 1
                    first_seen = prior["first_seen"]
                    row = self.connection.execute(
                        "SELECT last_changed FROM jobs WHERE job_uid = ?", (uid,)
                    ).fetchone()
                    last_changed = row["last_changed"]
                self.connection.execute(
                    """
                    INSERT INTO jobs(job_uid, canonical_url, content_fingerprint, job_json, first_seen, last_seen, last_changed, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(job_uid) DO UPDATE SET
                      canonical_url=excluded.canonical_url,
                      content_fingerprint=excluded.content_fingerprint,
                      job_json=excluded.job_json,
                      last_seen=excluded.last_seen,
                      last_changed=excluded.last_changed,
                      status=excluded.status
                    """,
                    (
                        uid,
                        job.get("canonical_url"),
                        job["content_fingerprint"],
                        json.dumps(job, ensure_ascii=False, sort_keys=True),
                        first_seen,
                        timestamp,
                        last_changed,
                        job.get("status", "unknown"),
                    ),
                )
                for alias in aliases:
                    self.connection.execute(
                        "INSERT OR IGNORE INTO job_aliases(alias_key, job_uid) VALUES (?, ?)",
                        (alias, uid),
                    )
                for provenance in job.get("provenance", []):
                    source_id = provenance.get("source_id")
                    if source_id not in seen_by_source:
                        continue
                    seen_by_source[source_id].add(uid)
                    authoritative = int(authoritative_by_source.get(source_id, False))
                    self.connection.execute(
                        """
                        INSERT INTO source_jobs(source_id, job_uid, authoritative, first_seen, last_seen, missed_successful_snapshots, active)
                        VALUES (?, ?, ?, ?, ?, 0, 1)
                        ON CONFLICT(source_id, job_uid) DO UPDATE SET
                          authoritative=excluded.authoritative,
                          last_seen=excluded.last_seen,
                          missed_successful_snapshots=0,
                          active=1
                        """,
                        (source_id, uid, authoritative, timestamp, timestamp),
                    )
                    self.connection.execute(
                        "INSERT OR REPLACE INTO observations(run_id, source_id, job_uid, observed_at, source_url) VALUES (?, ?, ?, ?, ?)",
                        (
                            run_id,
                            source_id,
                            uid,
                            provenance.get("observed_at", timestamp),
                            provenance.get("source_url"),
                        ),
                    )
            for result in results:
                if not (result.success and result.complete_snapshot and result.authoritative):
                    continue
                seen = seen_by_source[result.source_id]
                rows = self.connection.execute(
                    "SELECT job_uid, missed_successful_snapshots FROM source_jobs WHERE source_id = ? AND active = 1",
                    (result.source_id,),
                ).fetchall()
                for row in rows:
                    if row["job_uid"] in seen:
                        continue
                    misses = row["missed_successful_snapshots"] + 1
                    self.connection.execute(
                        "UPDATE source_jobs SET missed_successful_snapshots = ?, active = ? WHERE source_id = ? AND job_uid = ?",
                        (
                            misses,
                            int(misses < close_after_misses),
                            result.source_id,
                            row["job_uid"],
                        ),
                    )
            all_rows = self.connection.execute(
                "SELECT job_uid, status, job_json FROM jobs"
            ).fetchall()
            for row in all_rows:
                job = json.loads(row["job_json"])
                expired = job.get("freshness_status") == "expired"
                authoritative_rows = self.connection.execute(
                    "SELECT active FROM source_jobs WHERE job_uid = ? AND authoritative = 1",
                    (row["job_uid"],),
                ).fetchall()
                if expired:
                    status = "expired"
                elif any(item["active"] for item in authoritative_rows):
                    status = "open"
                elif authoritative_rows:
                    status = "closed"
                else:
                    status = "unknown"
                old_status = before_status.get(row["job_uid"], row["status"])
                if old_status != "closed" and status == "closed":
                    counts["closed"] += 1
                if old_status == "closed" and status == "open":
                    counts["reopened"] += 1
                job["status"] = status
                self.connection.execute(
                    "UPDATE jobs SET status = ?, job_json = ? WHERE job_uid = ?",
                    (status, json.dumps(job, ensure_ascii=False, sort_keys=True), row["job_uid"]),
                )
            success_count = sum(1 for result in results if result.success)
            self.connection.execute(
                "UPDATE runs SET finished_at = ?, success_count = ?, error_count = ? WHERE run_id = ?",
                (timestamp, success_count, len(results) - success_count, run_id),
            )
        return counts

    def list_jobs(self, status: str, limit: int) -> List[Dict[str, Any]]:
        if status == "all":
            rows = self.connection.execute(
                "SELECT job_json FROM jobs ORDER BY last_seen DESC LIMIT ?", (limit,)
            ).fetchall()
        else:
            rows = self.connection.execute(
                "SELECT job_json FROM jobs WHERE status = ? ORDER BY last_seen DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        return [json.loads(row["job_json"]) for row in rows]


def collect_source(
    source: Dict[str, Any], context: CollectionContext
) -> SourceResult:
    adapter_class = ADAPTERS[source["provider"]]
    adapter = adapter_class()
    try:
        return adapter.collect(source, context)
    except Exception as exc:
        return SourceResult(
            source_id=source["id"],
            provider=source["provider"],
            success=False,
            complete_snapshot=False,
            authoritative=adapter.authoritative,
            error=f"{type(exc).__name__}: {safe_error_message(exc)}",
            requests=adapter.plan(source),
        )


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise


def write_jsonl(jobs: Sequence[Dict[str, Any]], destination: Optional[str]) -> None:
    text = "".join(json.dumps(job, ensure_ascii=False, sort_keys=True) + "\n" for job in jobs)
    if not destination or destination == "-":
        sys.stdout.write(text)
    else:
        _atomic_write_text(Path(destination).resolve(), text)


def write_report(report: Dict[str, Any], destination: Optional[str]) -> None:
    text = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if destination:
        _atomic_write_text(Path(destination).resolve(), text)
    else:
        sys.stderr.write(text)


def dry_run_report(config: Dict[str, Any], config_path: Path) -> Dict[str, Any]:
    planned = []
    for source in config["sources"]:
        if source.get("enabled", True) is False:
            continue
        adapter = ADAPTERS[source["provider"]]
        planned.append(
            {
                "source_id": source["id"],
                "provider": source["provider"],
                "requests": adapter.plan(source),
                "network_requests_sent": 0,
            }
        )
    return {
        "mode": "dry-run",
        "config": str(config_path),
        "valid": True,
        "network_requests_sent": 0,
        "sources": planned,
    }


def command_collect(args: argparse.Namespace) -> int:
    config_path = Path(args.config).resolve()
    config, defaults = load_config(config_path)
    if args.dry_run:
        print(json.dumps(dry_run_report(config, config_path), ensure_ascii=False, indent=2))
        return 0
    if args.live == bool(args.fixtures_dir):
        raise ConfigError("choose exactly one of --live or --fixtures-dir (or use --dry-run)")
    if args.live:
        fetcher: BaseFetcher = NetworkFetcher(defaults)
        mode = "live"
    else:
        fetcher = FixtureFetcher(Path(args.fixtures_dir), int(defaults["max_response_bytes"]))
        mode = "fixtures"
    started = utc_now()
    context = CollectionContext(
        fetcher=fetcher,
        config_dir=config_path.parent,
        now=started,
        defaults=defaults,
        mode=mode,
    )
    enabled_sources = [source for source in config["sources"] if source.get("enabled", True) is not False]
    results = [collect_source(source, context) for source in enabled_sources]
    raw_jobs = [job for result in results if result.success for job in result.jobs]
    deduped = dedupe_jobs(raw_jobs, started, defaults)
    run_id = str(uuid.uuid4())
    delta = {"new": None, "changed": None, "unchanged": None, "closed": None, "reopened": None}
    warnings = [warning for result in results for warning in result.warnings]
    if args.state:
        store = StateStore(Path(args.state).resolve())
        try:
            delta = store.update(
                run_id,
                isoformat(started),
                mode,
                results,
                deduped,
                int(defaults["close_after_misses"]),
            )
        finally:
            store.close()
    else:
        warnings.append("state_disabled_no_incremental_tracking")
    filters = config.get("filters") or {}
    matched = [job for job in deduped if job_matches_filters(job, filters, started)]
    write_jsonl(matched, args.output)
    success_count = sum(1 for result in results if result.success)
    error_count = len(results) - success_count
    authoritative_results = [result for result in results if result.authoritative]
    report = {
        "run_id": run_id,
        "mode": mode,
        "started_at": isoformat(started),
        "finished_at": isoformat(utc_now()),
        "config": str(config_path),
        "complete_snapshot": bool(authoritative_results)
        and all(result.success and result.complete_snapshot for result in authoritative_results),
        "counts": {
            "sources": len(results),
            "sources_succeeded": success_count,
            "sources_failed": error_count,
            "raw": len(raw_jobs),
            "deduped": len(deduped),
            "matched_filters": len(matched),
            **delta,
        },
        "filters": filters,
        "sources": [result.report() for result in results],
        "errors": [
            {"source_id": result.source_id, "provider": result.provider, "error": result.error}
            for result in results
            if not result.success
        ],
        "warnings": sorted(set(warnings)),
    }
    write_report(report, args.report)
    if not results or success_count == 0:
        return 3
    if error_count:
        return 4
    return 0


def command_state(args: argparse.Namespace) -> int:
    path = Path(args.state).resolve()
    if not path.exists():
        raise ConfigError(f"state database does not exist: {path}")
    store = StateStore(path)
    try:
        jobs = store.list_jobs(args.status, args.limit)
    finally:
        store.close()
    write_jsonl(jobs, args.output)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Collect and incrementally track public job postings with provenance."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    collect_parser = subparsers.add_parser("collect", help="validate or collect configured sources")
    collect_parser.add_argument("--config", required=True, help="JSON source configuration")
    mode = collect_parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="validate and print a zero-network request plan")
    mode.add_argument("--live", action="store_true", help="perform guarded live public GET requests")
    mode.add_argument("--fixtures-dir", help="perform an offline fixture-backed run")
    collect_parser.add_argument("--output", default="-", help="normalized JSONL path, or - for stdout")
    collect_parser.add_argument("--report", help="run report JSON path; defaults to stderr")
    collect_parser.add_argument("--state", help="optional SQLite path for incremental state")
    collect_parser.set_defaults(handler=command_collect)

    state_parser = subparsers.add_parser("state", help="read current jobs from the SQLite state")
    state_parser.add_argument("--state", required=True, help="SQLite state path")
    state_parser.add_argument(
        "--status", choices=("open", "closed", "expired", "unknown", "all"), default="open"
    )
    state_parser.add_argument("--limit", type=int, default=100)
    state_parser.add_argument("--output", default="-", help="JSONL path, or - for stdout")
    state_parser.set_defaults(handler=command_state)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "limit", 1) < 1 or getattr(args, "limit", 1) > 10000:
        parser.error("--limit must be between 1 and 10000")
    try:
        return int(args.handler(args))
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
