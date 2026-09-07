from __future__ import annotations

import contextlib
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
import urllib.request


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPT = SKILL_DIR / "scripts" / "job_radar.py"
FIXTURES = Path(__file__).resolve().parent / "fixtures"

spec = importlib.util.spec_from_file_location("pmhub_job_radar", SCRIPT)
radar = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = radar
spec.loader.exec_module(radar)


class UrlAndDedupeTests(unittest.TestCase):
    def test_canonical_url_removes_tracking_and_fragment_but_keeps_job_id(self) -> None:
        url = "HTTPS://Jobs.Example.com:443/opening/123/?utm_source=x&lang=zh&ref=abc#apply"
        self.assertEqual(
            radar.canonicalize_url(url),
            "https://jobs.example.com/opening/123?lang=zh",
        )

    def test_content_fingerprint_dedupes_cross_source_and_keeps_provenance(self) -> None:
        now = radar.parse_datetime("2026-09-07T00:00:00Z")
        defaults = dict(radar.DEFAULTS)
        source_a = {"id": "a", "provider": "greenhouse", "company": "Acme"}
        source_b = {"id": "b", "provider": "lever", "company": "Acme"}
        common = {
            "company": "Acme",
            "title": "AI Product Manager",
            "description_text": "Build a measurable AI product with users, evaluation, release gates, adoption metrics, and documented failure reviews.",
            "locations": ["Shanghai"],
        }
        first = radar.finalize_job(
            {**common, "external_id": "gh-1", "job_url": "https://boards.example/jobs/1"},
            source=source_a,
            source_class="official_ats",
            fetched_via="test",
            source_url="https://api.example/a",
            now=now,
            defaults=defaults,
        )
        second = radar.finalize_job(
            {**common, "external_id": "lever-1", "job_url": "https://jobs.example/lever-1"},
            source=source_b,
            source_class="official_ats",
            fetched_via="test",
            source_url="https://api.example/b",
            now=now,
            defaults=defaults,
        )
        merged = radar.dedupe_jobs([first, second], now, defaults)
        self.assertEqual(len(merged), 1)
        self.assertEqual({p["source_id"] for p in merged[0]["provenance"]}, {"a", "b"})
        self.assertIn("deduplicated_multi_source", merged[0]["quality_flags"])

    def test_same_company_title_location_with_different_content_is_not_merged(self) -> None:
        now = radar.parse_datetime("2026-09-07T00:00:00Z")
        defaults = dict(radar.DEFAULTS)
        source = {"id": "a", "provider": "greenhouse", "company": "Acme"}
        jobs = []
        for index, description in enumerate(("Own consumer AI search.", "Own enterprise AI search."), 1):
            jobs.append(
                radar.finalize_job(
                    {
                        "external_id": index,
                        "company": "Acme",
                        "title": "Product Manager",
                        "description_text": description,
                        "locations": ["Beijing"],
                        "job_url": f"https://careers.example/jobs/{index}",
                    },
                    source=source,
                    source_class="official_ats",
                    fetched_via="test",
                    source_url="https://api.example/jobs",
                    now=now,
                    defaults=defaults,
                )
            )
        self.assertEqual(len(radar.dedupe_jobs(jobs, now, defaults)), 2)


class SecurityTests(unittest.TestCase):
    def _write_config(self, directory: Path, source: dict) -> Path:
        path = directory / "sources.json"
        path.write_text(json.dumps({"schema_version": "1", "sources": [source]}), encoding="utf-8")
        return path

    def test_only_http_and_https_are_allowed_for_generic_fetch(self) -> None:
        with self.assertRaises(radar.ConfigError):
            radar.validate_url_static("file:///etc/passwd")

    def test_private_and_local_targets_are_blocked(self) -> None:
        for url in (
            "http://127.0.0.1/jobs",
            "http://[::1]/jobs",
            "http://169.254.169.254/latest/meta-data",
            "http://localhost/jobs",
        ):
            with self.subTest(url=url), self.assertRaises(radar.ConfigError):
                radar.validate_url_static(url)

    def test_restricted_platform_direct_fetch_is_blocked(self) -> None:
        for url in (
            "https://www.zhipin.com/job/1",
            "https://www.lagou.com/jobs/1",
            "https://www.linkedin.com/jobs/view/1",
        ):
            with self.subTest(url=url), self.assertRaises(radar.ConfigError):
                radar.validate_url_static(url)

    def test_sensitive_headers_or_credentials_are_rejected_from_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_config(
                Path(tmp),
                {
                    "id": "site",
                    "provider": "jsonld",
                    "company": "Acme",
                    "urls": ["https://careers.example.com/jobs/1"],
                    "headers": {"Cookie": "session=secret"},
                },
            )
            with self.assertRaises(radar.ConfigError):
                radar.load_config(path)

    def test_google_cse_cannot_read_arbitrary_environment_variables(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_config(
                Path(tmp),
                {
                    "id": "search",
                    "provider": "google_cse",
                    "query": "product manager jobs",
                    "api_key_env": "AWS_SECRET_ACCESS_KEY",
                    "cx_env": "PMHUB_GOOGLE_CSE_CX",
                },
            )
            with self.assertRaises(radar.ConfigError):
                radar.load_config(path)

    def test_dns_resolution_to_private_ip_is_blocked(self) -> None:
        fetcher = radar.NetworkFetcher(dict(radar.DEFAULTS))
        private_resolution = [(2, 1, 6, "", ("127.0.0.1", 0))]
        with mock.patch.object(radar.socket, "getaddrinfo", return_value=private_resolution):
            with self.assertRaises(radar.FetchError):
                fetcher._validate_target("https://careers.example.com/jobs/1", documented_api=False)

    def test_redirect_to_private_ip_is_blocked_before_following(self) -> None:
        fetcher = radar.NetworkFetcher(dict(radar.DEFAULTS))
        handler = radar._SafeRedirectHandler(fetcher._validate_target, False)
        request = urllib.request.Request("https://careers.example.com/jobs/1")
        with self.assertRaises(radar.FetchError):
            handler.redirect_request(
                request,
                None,
                302,
                "Found",
                {},
                "http://127.0.0.1/internal",
            )

    def test_dns_rebinding_is_blocked_on_connection_resolution(self) -> None:
        fetcher = radar.NetworkFetcher(dict(radar.DEFAULTS))
        public = [(2, 1, 6, "", ("8.8.8.8", 443))]
        private = [(2, 1, 6, "", ("127.0.0.1", 443))]
        with mock.patch.object(
            radar.socket, "getaddrinfo", side_effect=[public, private]
        ) as resolver:
            with self.assertRaises(radar.FetchError):
                fetcher._raw_get(
                    "https://careers.example.com/jobs/1", documented_api=False
                )
        self.assertEqual(resolver.call_count, 2)

    def test_https_pinned_connection_keeps_original_tls_hostname(self) -> None:
        context = mock.Mock()
        plain_socket = mock.Mock()
        wrapped_socket = mock.Mock()
        context.wrap_socket.return_value = wrapped_socket
        connection = radar._PinnedHTTPSConnection(
            "careers.example.com",
            pinned_addresses=("8.8.8.8",),
            context=context,
        )
        with mock.patch.object(
            radar, "_connect_pinned_socket", return_value=plain_socket
        ):
            connection.connect()
        context.wrap_socket.assert_called_once_with(
            plain_socket, server_hostname="careers.example.com"
        )

    def test_retry_after_over_sleep_cap_stops_without_early_retry(self) -> None:
        fetcher = radar.NetworkFetcher(dict(radar.DEFAULTS))
        error = radar.urllib.error.HTTPError(
            "https://example.com/jobs",
            429,
            "Too Many Requests",
            {"Retry-After": "3600"},
            None,
        )
        opener = mock.Mock()
        opener.open.side_effect = error
        with mock.patch.object(fetcher, "_validate_target", return_value="example.com"), mock.patch.object(
            radar.urllib.request, "build_opener", return_value=opener
        ), mock.patch.object(radar.time, "sleep") as sleeper:
            with self.assertRaisesRegex(radar.FetchError, "stopped instead of retrying early"):
                fetcher._raw_get("https://example.com/jobs", documented_api=False)
        sleeper.assert_not_called()

    def test_robots_rate_directives_raise_effective_host_interval(self) -> None:
        fetcher = radar.NetworkFetcher(dict(radar.DEFAULTS))
        parser = radar.urllib.robotparser.RobotFileParser()
        parser.parse(
            ["User-agent: PMHubJobRadar", "Allow: /", "Crawl-delay: 7", "Request-rate: 1/20"]
        )
        fetcher._apply_robots_rate_policy("https://careers.example.com/jobs/1", parser)
        self.assertEqual(fetcher.robots_interval_by_host["careers.example.com"], 20.0)

    def test_redirect_target_must_pass_its_own_robots_policy(self) -> None:
        fetcher = radar.NetworkFetcher(dict(radar.DEFAULTS))
        parser = radar.urllib.robotparser.RobotFileParser()
        parser.parse(["User-agent: *", "Disallow: /private"])

        class RedirectingOpener:
            def __init__(self, redirect_handler: object) -> None:
                self.redirect_handler = redirect_handler

            def open(self, request: object, timeout: float) -> object:
                return self.redirect_handler.redirect_request(
                    request,
                    None,
                    302,
                    "Found",
                    {},
                    "https://other.example/private",
                )

        def fake_build_opener(*handlers: object) -> object:
            redirect = next(
                handler
                for handler in handlers
                if isinstance(handler, radar._SafeRedirectHandler)
            )
            return RedirectingOpener(redirect)

        with mock.patch.object(fetcher, "_validate_target", return_value="example.com"), mock.patch.object(
            fetcher, "_robots_parser", return_value=parser
        ) as robots, mock.patch.object(
            radar.urllib.request, "build_opener", side_effect=fake_build_opener
        ):
            with self.assertRaisesRegex(radar.FetchError, "redirect target"):
                fetcher._raw_get("https://example.com/start", documented_api=False)
        robots.assert_called_once_with("https://other.example/private")

    def test_cse_key_and_engine_id_are_both_redacted(self) -> None:
        redacted = radar.redact_url(
            "https://customsearch.googleapis.com/customsearch/v1?key=secret&cx=engine&q=jobs"
        )
        self.assertNotIn("secret", redacted)
        self.assertNotIn("engine", redacted)
        self.assertEqual(redacted.count("%3Credacted%3E"), 2)

    def test_unsafe_job_and_apply_urls_are_removed(self) -> None:
        now = radar.parse_datetime("2026-09-07T00:00:00Z")
        source = {"id": "site", "provider": "jsonld", "company": "Acme"}
        job = radar.finalize_job(
            {
                "title": "PM",
                "job_url": "file:///etc/passwd",
                "apply_url": "http://127.0.0.1/apply",
            },
            source=source,
            source_class="company_site",
            fetched_via="test",
            source_url="https://careers.example.com/jobs/1",
            now=now,
            defaults=dict(radar.DEFAULTS),
        )
        self.assertEqual(job["job_url"], "")
        self.assertIsNone(job["apply_url"])
        self.assertIn("unsafe_job_url_removed", job["quality_flags"])
        self.assertIn("unsafe_apply_url_removed", job["quality_flags"])

    def test_malformed_provider_record_is_isolated_as_source_failure(self) -> None:
        class MalformedFetcher(radar.BaseFetcher):
            def get(self, url: str, *, documented_api: bool = False) -> bytes:
                return json.dumps(
                    {"jobs": [{"id": 1, "title": "PM", "offices": 7}]}
                ).encode()

        context = radar.CollectionContext(
            fetcher=MalformedFetcher(),
            config_dir=Path("."),
            now=radar.parse_datetime("2026-09-07T00:00:00Z"),
            defaults=dict(radar.DEFAULTS),
            mode="test",
        )
        result = radar.collect_source(
            {
                "id": "bad",
                "provider": "greenhouse",
                "company": "Acme",
                "board_token": "acme",
            },
            context,
        )
        self.assertFalse(result.success)
        self.assertIn("TypeError", result.error)

    def test_manual_import_rejects_absolute_escape_and_oversized_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_dir = root / "config"
            config_dir.mkdir()
            outside = root / "outside.json"
            outside.write_text("[]", encoding="utf-8")
            source = {
                "id": "manual",
                "provider": "manual_import",
                "path": str(outside),
                "format": "json",
            }
            context = radar.CollectionContext(
                fetcher=mock.Mock(),
                config_dir=config_dir,
                now=radar.parse_datetime("2026-09-07T00:00:00Z"),
                defaults=dict(radar.DEFAULTS),
                mode="test",
            )
            with self.assertRaisesRegex(radar.ConfigError, "must be relative"):
                radar.ManualImportAdapter().collect(source, context)

            inside = config_dir / "large.json"
            inside.write_bytes(b"[" + b" " * 32 + b"]")
            source["path"] = "large.json"
            context.defaults = {**radar.DEFAULTS, "max_response_bytes": 16}
            with self.assertRaisesRegex(radar.ConfigError, "exceeds 16 bytes"):
                radar.ManualImportAdapter().collect(source, context)

    def test_fixture_path_cannot_escape_fixture_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / "http_map.json").write_text(
                json.dumps({"https://example.com/jobs": "../secret.txt"}), encoding="utf-8"
            )
            fetcher = radar.FixtureFetcher(directory, 1024)
            with self.assertRaises(radar.FetchError):
                fetcher.get("https://example.com/jobs")

    def test_response_size_limit_is_enforced_offline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / "http_map.json").write_text(
                json.dumps({"https://example.com/jobs": "large.json"}), encoding="utf-8"
            )
            (directory / "large.json").write_bytes(b"x" * 33)
            fetcher = radar.FixtureFetcher(directory, 32)
            with self.assertRaises(radar.FetchError):
                fetcher.get("https://example.com/jobs")


class PaginationGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = radar.parse_datetime("2026-09-07T00:00:00Z")
        self.defaults = dict(radar.DEFAULTS)

    def _context(self, fetcher: object) -> object:
        return radar.CollectionContext(
            fetcher=fetcher,
            config_dir=Path("."),
            now=self.now,
            defaults=self.defaults,
            mode="test",
        )

    def test_lever_repeated_page_stops_with_warning(self) -> None:
        page = [
            {
                "id": str(index),
                "text": f"PM {index}",
                "descriptionPlain": "Role description",
                "hostedUrl": f"https://jobs.example.com/{index}",
            }
            for index in range(100)
        ]

        class RepeatingFetcher(radar.BaseFetcher):
            def __init__(self) -> None:
                self.calls = 0

            def get(self, url: str, *, documented_api: bool = False) -> bytes:
                self.calls += 1
                return json.dumps(page).encode()

        fetcher = RepeatingFetcher()
        result = radar.LeverAdapter().collect(
            {
                "id": "lever",
                "provider": "lever",
                "company": "Acme",
                "site": "acme",
                "max_results": 300,
            },
            self._context(fetcher),
        )
        self.assertEqual(fetcher.calls, 2)
        self.assertFalse(result.complete_snapshot)
        self.assertIn("pagination_stalled_repeated_page", result.warnings)

    def test_smartrecruiters_page_limit_is_fail_closed(self) -> None:
        class PagedFetcher(radar.BaseFetcher):
            def __init__(self) -> None:
                self.calls = 0

            def get(self, url: str, *, documented_api: bool = False) -> bytes:
                self.calls += 1
                if "/postings/" in url.split("?", 1)[0]:
                    return b"{}"
                offset = int(
                    radar.urllib.parse.parse_qs(radar.urllib.parse.urlsplit(url).query)[
                        "offset"
                    ][0]
                )
                page = [
                    {"id": str(offset + index), "name": f"PM {offset + index}"}
                    for index in range(100)
                ]
                return json.dumps({"totalFound": 1000, "content": page}).encode()

        fetcher = PagedFetcher()
        result = radar.SmartRecruitersAdapter().collect(
            {
                "id": "sr",
                "provider": "smartrecruiters",
                "company": "Acme",
                "company_identifier": "acme",
                "max_results": 500,
                "max_pages": 1,
            },
            self._context(fetcher),
        )
        self.assertFalse(result.complete_snapshot)
        self.assertIn("page_limit_reached:1", result.warnings)

    def test_google_repeated_or_backward_cursor_stops(self) -> None:
        class CursorFetcher(radar.BaseFetcher):
            def __init__(self) -> None:
                self.calls = 0

            def get(self, url: str, *, documented_api: bool = False) -> bytes:
                self.calls += 1
                return json.dumps(
                    {
                        "items": [
                            {
                                "title": "PM",
                                "link": "https://careers.example.com/jobs/1",
                            }
                        ],
                        "queries": {"nextPage": [{"startIndex": 1}]},
                    }
                ).encode()

        fetcher = CursorFetcher()
        result = radar.GoogleCseAdapter().collect(
            {
                "id": "search",
                "provider": "google_cse",
                "query": "PM jobs",
                "api_key_env": "PMHUB_GOOGLE_CSE_KEY",
                "cx_env": "PMHUB_GOOGLE_CSE_CX",
                "max_results": 20,
            },
            radar.CollectionContext(
                fetcher=fetcher,
                config_dir=Path("."),
                now=self.now,
                defaults=self.defaults,
                mode="fixtures",
            ),
        )
        self.assertEqual(fetcher.calls, 1)
        self.assertIn("pagination_stalled_invalid_cursor", result.warnings)


class OfflineIntegrationTests(unittest.TestCase):
    def test_all_providers_parse_offline_and_cross_source_duplicate_is_removed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            output = directory / "jobs.jsonl"
            report_path = directory / "report.json"
            state = directory / "state.sqlite"
            code = radar.main(
                [
                    "collect",
                    "--config",
                    str(FIXTURES / "sources.json"),
                    "--fixtures-dir",
                    str(FIXTURES),
                    "--output",
                    str(output),
                    "--report",
                    str(report_path),
                    "--state",
                    str(state),
                ]
            )
            self.assertEqual(code, 0)
            jobs = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["counts"]["sources_succeeded"], 7)
            self.assertEqual(report["counts"]["raw"], 7)
            self.assertEqual(report["counts"]["deduped"], 6)
            self.assertEqual(len(jobs), 6)
            self.assertTrue(report["complete_snapshot"])
            self.assertFalse(any("zhipin.com" in job["canonical_url"] and "discovery_only" in job["quality_flags"] for job in jobs))
            merged = next(job for job in jobs if job["title"] == "AI Product Manager")
            self.assertEqual(len(merged["provenance"]), 2)

    def test_repeat_fixture_run_is_incremental_and_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            state = directory / "state.sqlite"
            for run_number in (1, 2):
                code = radar.main(
                    [
                        "collect",
                        "--config",
                        str(FIXTURES / "sources.json"),
                        "--fixtures-dir",
                        str(FIXTURES),
                        "--output",
                        str(directory / f"jobs-{run_number}.jsonl"),
                        "--report",
                        str(directory / f"report-{run_number}.json"),
                        "--state",
                        str(state),
                    ]
                )
                self.assertEqual(code, 0)
            second = json.loads((directory / "report-2.json").read_text(encoding="utf-8"))
            self.assertEqual(second["counts"]["new"], 0)
            self.assertEqual(second["counts"]["changed"], 0)
            self.assertEqual(second["counts"]["unchanged"], 6)

    def test_source_failure_is_isolated_and_returns_partial_exit_code(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            config = {
                "schema_version": "1",
                "sources": [
                    {"id": "good", "provider": "greenhouse", "company": "Acme", "board_token": "acme"},
                    {"id": "bad", "provider": "ashby", "company": "Missing", "board": "Missing"},
                ],
            }
            config_path = directory / "sources.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            output = directory / "jobs.jsonl"
            report_path = directory / "report.json"
            code = radar.main(
                [
                    "collect",
                    "--config",
                    str(config_path),
                    "--fixtures-dir",
                    str(FIXTURES),
                    "--output",
                    str(output),
                    "--report",
                    str(report_path),
                ]
            )
            self.assertEqual(code, 4)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["counts"]["sources_succeeded"], 1)
            self.assertEqual(report["counts"]["sources_failed"], 1)
            self.assertEqual(len(output.read_text(encoding="utf-8").splitlines()), 1)

    def test_dry_run_performs_no_fetch_and_redacts_search_key(self) -> None:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = radar.main(
                ["collect", "--config", str(FIXTURES / "sources.json"), "--dry-run"]
            )
        self.assertEqual(code, 0)
        report = json.loads(stdout.getvalue())
        self.assertEqual(report["network_requests_sent"], 0)
        serialized = json.dumps(report)
        self.assertNotIn("fixture-key", serialized)
        self.assertIn("redacted", serialized)


class StateLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = radar.parse_datetime("2026-09-07T00:00:00Z")
        self.defaults = dict(radar.DEFAULTS)
        self.source = {"id": "official", "provider": "greenhouse", "company": "Acme"}
        self.job = radar.finalize_job(
            {
                "external_id": "1",
                "company": "Acme",
                "title": "AI Product Manager",
                "description_text": "Own an AI product with representative evaluation and real user evidence.",
                "locations": ["Shanghai"],
                "posted_at": "2026-09-06",
                "job_url": "https://careers.example.com/jobs/1",
            },
            source=self.source,
            source_class="official_ats",
            fetched_via="test",
            source_url="https://api.example.com/jobs",
            now=self.now,
            defaults=self.defaults,
        )

    def _result(self, success: bool, complete: bool, jobs: list) -> object:
        return radar.SourceResult(
            source_id="official",
            provider="greenhouse",
            success=success,
            complete_snapshot=complete,
            authoritative=True,
            jobs=jobs,
            error=None if success else "temporary error",
        )

    def test_closes_only_after_two_successful_complete_misses(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = radar.StateStore(Path(tmp) / "state.sqlite")
            try:
                store.update("run-1", "2026-09-07T00:00:00Z", "fixtures", [self._result(True, True, [self.job])], [self.job], 2)
                first_miss = store.update("run-2", "2026-09-08T00:00:00Z", "fixtures", [self._result(True, True, [])], [], 2)
                self.assertEqual(first_miss["closed"], 0)
                self.assertEqual(len(store.list_jobs("open", 10)), 1)
                second_miss = store.update("run-3", "2026-09-09T00:00:00Z", "fixtures", [self._result(True, True, [])], [], 2)
                self.assertEqual(second_miss["closed"], 1)
                self.assertEqual(len(store.list_jobs("closed", 10)), 1)
            finally:
                store.close()

    def test_failed_or_partial_run_never_advances_closure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = radar.StateStore(Path(tmp) / "state.sqlite")
            try:
                store.update("run-1", "2026-09-07T00:00:00Z", "fixtures", [self._result(True, True, [self.job])], [self.job], 1)
                failed = store.update("run-2", "2026-09-08T00:00:00Z", "fixtures", [self._result(False, False, [])], [], 1)
                self.assertEqual(failed["closed"], 0)
                self.assertEqual(len(store.list_jobs("open", 10)), 1)
            finally:
                store.close()

    def test_same_url_content_change_is_reported_as_changed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = radar.StateStore(Path(tmp) / "state.sqlite")
            try:
                store.update("run-1", "2026-09-07T00:00:00Z", "fixtures", [self._result(True, True, [self.job])], [self.job], 2)
                changed = copy.deepcopy(self.job)
                changed["description_text"] += " Added cost and latency requirements."
                changed["content_fingerprint"] = radar.content_fingerprint(changed)
                delta = store.update("run-2", "2026-09-08T00:00:00Z", "fixtures", [self._result(True, True, [changed])], [changed], 2)
                self.assertEqual(delta["changed"], 1)
                self.assertEqual(delta["new"], 0)
            finally:
                store.close()

    def test_reappearance_after_close_counts_as_reopened(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = radar.StateStore(Path(tmp) / "state.sqlite")
            try:
                store.update(
                    "run-1",
                    "2026-09-07T00:00:00Z",
                    "fixtures",
                    [self._result(True, True, [self.job])],
                    [self.job],
                    1,
                )
                store.update(
                    "run-2",
                    "2026-09-08T00:00:00Z",
                    "fixtures",
                    [self._result(True, True, [])],
                    [],
                    1,
                )
                reopened = store.update(
                    "run-3",
                    "2026-09-09T00:00:00Z",
                    "fixtures",
                    [self._result(True, True, [self.job])],
                    [self.job],
                    1,
                )
                self.assertEqual(reopened["reopened"], 1)
                self.assertEqual(len(store.list_jobs("open", 10)), 1)
            finally:
                store.close()

    def test_cross_source_dedupe_uid_stays_stable_when_one_source_fails(self) -> None:
        source_b = {"id": "backup", "provider": "lever", "company": "Acme"}
        raw = {
            "external_id": "backup-1",
            "company": "Acme",
            "title": self.job["title"],
            "description_text": self.job["description_text"],
            "locations": self.job["locations"],
            "posted_at": self.job["posted_at"],
            "job_url": "https://z-backup.example.com/jobs/1",
        }
        backup_job = radar.finalize_job(
            raw,
            source=source_b,
            source_class="official_ats",
            fetched_via="test",
            source_url="https://api.example.com/backup",
            now=self.now,
            defaults=self.defaults,
        )
        official_result = self._result(True, True, [self.job])
        backup_result = radar.SourceResult(
            source_id="backup",
            provider="lever",
            success=True,
            complete_snapshot=True,
            authoritative=True,
            jobs=[backup_job],
        )
        with tempfile.TemporaryDirectory() as tmp:
            store = radar.StateStore(Path(tmp) / "state.sqlite")
            try:
                merged = radar.dedupe_jobs(
                    [self.job, backup_job], self.now, self.defaults
                )
                first = store.update(
                    "run-1",
                    "2026-09-07T00:00:00Z",
                    "fixtures",
                    [official_result, backup_result],
                    merged,
                    2,
                )
                self.assertEqual(first["new"], 1)
                failed_official = self._result(False, False, [])
                second = store.update(
                    "run-2",
                    "2026-09-08T00:00:00Z",
                    "fixtures",
                    [failed_official, backup_result],
                    [backup_job],
                    2,
                )
                self.assertEqual(second["new"], 0)
                self.assertEqual(second["unchanged"], 1)
                self.assertEqual(len(store.list_jobs("all", 10)), 1)
            finally:
                store.close()

    def test_same_source_identical_text_different_ids_remain_separate_in_state(self) -> None:
        second = radar.finalize_job(
            {
                "external_id": "2",
                "company": self.job["company"],
                "title": self.job["title"],
                "description_text": self.job["description_text"],
                "locations": self.job["locations"],
                "posted_at": self.job["posted_at"],
                "job_url": "https://careers.example.com/jobs/2",
            },
            source=self.source,
            source_class="official_ats",
            fetched_via="test",
            source_url="https://api.example.com/jobs",
            now=self.now,
            defaults=self.defaults,
        )
        jobs = radar.dedupe_jobs([self.job, second], self.now, self.defaults)
        self.assertEqual(len(jobs), 2)
        self.assertTrue(
            all(
                "possible_duplicate_same_source_identity_conflict"
                in job["quality_flags"]
                for job in jobs
            )
        )
        with tempfile.TemporaryDirectory() as tmp:
            store = radar.StateStore(Path(tmp) / "state.sqlite")
            try:
                delta = store.update(
                    "run-1",
                    "2026-09-07T00:00:00Z",
                    "fixtures",
                    [self._result(True, True, [self.job, second])],
                    jobs,
                    2,
                )
                self.assertEqual(delta["new"], 2)
                self.assertEqual(len(store.list_jobs("all", 10)), 2)
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
