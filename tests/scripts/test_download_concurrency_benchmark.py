import argparse
import tempfile
from pathlib import Path

import pytest

from autodrome.yt_downloader import YTDownloader
from scripts.benchmark_download_concurrency import (
    BenchmarkDownloader,
    prepare_output_root,
    render_markdown,
    summarize_runs,
    validate_arguments,
    validate_levels,
)


def test_experimental_downloader_does_not_widen_production_limit():
    assert BenchmarkDownloader(20).download_concurrency == 20
    with pytest.raises(ValueError, match="between 1 and 20"):
        BenchmarkDownloader(21)
    with pytest.raises(ValueError, match="between 1 and 4"):
        YTDownloader(download_concurrency=5)


def test_levels_must_be_unique_increasing_and_bounded():
    assert validate_levels([1, 2, 4, 8, 12, 20]) == [1, 2, 4, 8, 12, 20]
    for levels in ([], [2, 1], [1, 1], [0, 1], [1, 21]):
        with pytest.raises(ValueError):
            validate_levels(levels)


def test_output_root_is_new_and_below_system_temporary_directory(tmp_path):
    output = tmp_path / "benchmark-output"
    assert prepare_output_root(str(output)) == output.resolve()
    assert output.is_dir()
    with pytest.raises(ValueError, match="must not already exist"):
        prepare_output_root(str(output))
    with pytest.raises(ValueError, match="below"):
        prepare_output_root("/var/tmp/autodrome-benchmark")
    with pytest.raises(ValueError, match="absolute"):
        prepare_output_root("relative-benchmark")


def test_default_output_root_is_an_isolated_new_directory():
    output = prepare_output_root(None)
    try:
        assert output.parent == Path(tempfile.gettempdir()).resolve()
        assert output.name.startswith("autodrome-concurrency-benchmark-")
    finally:
        output.rmdir()


def test_real_run_requires_explicit_disposable_confirmation():
    args = argparse.Namespace(
        playlist_url="https://example.test/playlist",
        expected_tracks=20,
        levels=[1, 2, 4, 8, 12, 20],
        attempts=2,
        sample_interval=0.2,
        dry_run=False,
        confirm_disposable=False,
    )
    with pytest.raises(ValueError, match="confirm-disposable"):
        validate_arguments(args)
    args.dry_run = True
    validate_arguments(args)


def test_summary_keeps_supported_recommendation_conservative():
    runs = [
        {"concurrency": 1, "status": "passed", "throughput_tracks_per_second": 1.0},
        {"concurrency": 2, "status": "passed", "throughput_tracks_per_second": 1.9},
        {"concurrency": 4, "status": "passed", "throughput_tracks_per_second": 1.95},
        {"concurrency": 8, "status": "failed", "throughput_tracks_per_second": 1.2},
    ]
    summary = summarize_runs(runs)
    assert summary["highest_successful_experimental_level"] == 4
    assert summary["first_failed_level"] == 8
    assert summary["recommended_supported_level_on_this_host"] == 2
    assert summary["production_default_unchanged"] == 1
    assert summary["production_maximum_unchanged"] == 4


def test_markdown_records_environment_metrics_and_integrity():
    run = {
        "concurrency": 2,
        "status": "passed",
        "elapsed_seconds": 5.0,
        "throughput_tracks_per_second": 2.0,
        "peak_active_downloads": 2,
        "peak_ffmpeg_processes": 2,
        "peak_process_tree_cpu_percent": 125.0,
        "peak_process_tree_rss_mib": 256.0,
        "retry_attempts": 1,
        "throttling_errors": 0,
        "integrity": {"valid": True},
    }
    report = {
        "started_at": "2026-09-10T00:00:00+00:00",
        "environment": {
            "hostname": "test-host", "platform": "Linux", "cpu_model": "Test CPU",
            "cpu_count": 4, "total_memory_bytes": 1024, "ffmpeg": "ffmpeg test",
            "yt_dlp": "test", "git_revision": "abc123",
        },
        "runs": [run],
        "summary": summarize_runs([run]),
    }
    rendered = render_markdown(report)
    assert "| 2 | passed | 5.00 | 2.000 | 2 | 2 | 125.0 | 256.0 | 1 | 0 | yes |" in rendered
    assert "production default remains 1" in rendered
