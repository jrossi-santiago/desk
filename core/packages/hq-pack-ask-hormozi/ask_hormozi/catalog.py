from __future__ import annotations

import json
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .ingest import (
    DEFAULT_CHANNEL_URL,
    YOUTUBE_EXTRACTOR_ARGS,
    list_episodes,
)


@dataclass(frozen=True)
class CaptionAuditResult:
    episode_id: str
    title: str
    episode_url: str
    published: str
    duration_seconds: int
    manual_english: list[str]
    automatic_english: list[str]
    status: str
    error: str | None = None


def build_catalog(
    output_dir: Path,
    *,
    channel_url: str = DEFAULT_CHANNEL_URL,
    limit: int | None = None,
) -> dict[str, Any]:
    episodes = list_episodes(channel_url, limit=limit)
    return write_catalog(
        output_dir,
        episodes=episodes,
        channel_url=channel_url,
    )


def write_catalog(
    output_dir: Path,
    *,
    episodes: list[dict[str, Any]],
    channel_url: str,
) -> dict[str, Any]:
    output_dir = output_dir.expanduser().resolve()
    normalized = [
        _normalize_flat_episode(episode, position=index)
        for index, episode in enumerate(episodes, start=1)
    ]
    catalog = {
        "schema_version": 1,
        "channel": "MoreMozi",
        "channel_url": channel_url,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "episode_count": len(normalized),
        "episodes": normalized,
    }
    for episode in normalized:
        filename = f"{episode['episode_id'].lower()}.md"
        _write_text(
            output_dir / "episodes" / filename,
            render_catalog_episode(episode),
        )
    _write_text(
        output_dir / "catalog.json",
        json.dumps(catalog, indent=2, ensure_ascii=False) + "\n",
    )
    return catalog


def render_catalog_episode(episode: dict[str, Any]) -> str:
    metadata = {
        "episode_id": episode["episode_id"],
        "title": episode["title"],
        "episode_url": episode["episode_url"],
        "duration_seconds": episode["duration_seconds"],
        "channel": "MoreMozi",
        "source": "youtube_catalog",
    }
    lines = ["---"]
    lines.extend(
        f"{key}: {json.dumps(value, ensure_ascii=False, separators=(',', ':'))}"
        for key, value in metadata.items()
    )
    lines.extend(
        [
            "---",
            "",
            f"# {episode['title']}",
            "",
            f"Video: [{episode['episode_url']}]({episode['episode_url']})",
            f"Duration: {_format_duration(episode['duration_seconds'])}",
            "",
            "This catalog entry identifies the source video. Timestamped "
            "transcript passages are stored under `segments/` when the "
            "authorized transcript corpus is present.",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def audit_caption_coverage(
    *,
    output_file: Path,
    channel_url: str = DEFAULT_CHANNEL_URL,
    limit: int | None = None,
    jobs: int = 4,
    resume: bool = True,
    request_delay: float = 0,
    progress: Callable[[CaptionAuditResult, int, int], None] | None = None,
) -> dict[str, Any]:
    episodes = list_episodes(channel_url, limit=limit)
    output_file = output_file.expanduser().resolve()
    existing = _load_existing_audit(output_file) if resume else {}
    results_by_id = {
        str(episode["id"]): result
        for episode in episodes
        if (result := existing.get(str(episode["id"])))
    }
    verified_ids = {
        episode_id
        for episode_id, result in results_by_id.items()
        if result.status in {"captioned", "missing_english"}
    }
    pending = [
        episode
        for episode in episodes
        if str(episode["id"]) not in verified_ids
    ]
    total = len(pending)

    with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        futures = {
            pool.submit(
                inspect_caption_coverage,
                episode,
                request_delay=request_delay,
            ): episode
            for episode in pending
        }
        for completed, future in enumerate(as_completed(futures), start=1):
            episode = futures[future]
            try:
                result = future.result()
            except Exception as exc:
                video_id = str(episode["id"])
                result = CaptionAuditResult(
                    episode_id=video_id,
                    title=str(episode.get("title") or video_id),
                    episode_url=_episode_url(video_id),
                    published="",
                    duration_seconds=int(episode.get("duration") or 0),
                    manual_english=[],
                    automatic_english=[],
                    status="failed",
                    error=str(exc),
                )
            results_by_id[result.episode_id] = result
            snapshot = _build_audit_payload(
                episodes=episodes,
                results_by_id=results_by_id,
                channel_url=channel_url,
            )
            _write_text(
                output_file,
                json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n",
            )
            if progress:
                progress(result, completed, total)

    payload = _build_audit_payload(
        episodes=episodes,
        results_by_id=results_by_id,
        channel_url=channel_url,
    )
    _write_text(
        output_file,
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
    )
    return payload


def _build_audit_payload(
    *,
    episodes: list[dict[str, Any]],
    results_by_id: dict[str, CaptionAuditResult],
    channel_url: str,
) -> dict[str, Any]:
    results = [
        results_by_id[video_id]
        for episode in episodes
        if (video_id := str(episode["id"])) in results_by_id
    ]
    return {
        "schema_version": 1,
        "channel_url": channel_url,
        "audited_at": datetime.now(timezone.utc).isoformat(),
        "episode_count": len(episodes),
        "captioned_count": sum(
            result.status == "captioned" for result in results
        ),
        "missing_english_count": sum(
            result.status == "missing_english" for result in results
        ),
        "failed_count": sum(result.status == "failed" for result in results),
        "episodes": [asdict(result) for result in results],
    }


def inspect_caption_coverage(
    episode: dict[str, Any], *, request_delay: float = 0
) -> CaptionAuditResult:
    video_id = str(episode["id"])
    if request_delay > 0:
        time.sleep(request_delay)
    completed: subprocess.CompletedProcess[str] | None = None
    failures: list[str] = []
    info: dict[str, Any] | None = None
    for extractor_args in YOUTUBE_EXTRACTOR_ARGS:
        completed = subprocess.run(
            [
                "yt-dlp",
                "--no-warnings",
                "--skip-download",
                "--ignore-no-formats-error",
                "--dump-single-json",
                "--extractor-args",
                extractor_args,
                _episode_url(video_id),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            detail = completed.stderr.strip()
            failures.append(
                detail[-1_500:] if len(detail) > 1_500 else detail
            )
            continue
        info = json.loads(completed.stdout)
        if _english_languages(info.get("subtitles") or {}) or (
            _english_languages(info.get("automatic_captions") or {})
        ):
            break
    if info is None:
        detail = failures[-1] if failures else "unknown error"
        raise RuntimeError(f"yt-dlp failed for {video_id}: {detail}")
    manual = _english_languages(info.get("subtitles") or {})
    automatic = _english_languages(info.get("automatic_captions") or {})
    upload_date = str(info.get("upload_date") or "")
    published = (
        f"{upload_date[0:4]}-{upload_date[4:6]}-{upload_date[6:8]}"
        if len(upload_date) == 8
        else upload_date
    )
    return CaptionAuditResult(
        episode_id=video_id,
        title=str(info.get("title") or episode.get("title") or video_id),
        episode_url=_episode_url(video_id),
        published=published,
        duration_seconds=int(info.get("duration") or episode.get("duration") or 0),
        manual_english=manual,
        automatic_english=automatic,
        status="captioned" if manual or automatic else "missing_english",
    )


def _normalize_flat_episode(
    episode: dict[str, Any], *, position: int
) -> dict[str, Any]:
    video_id = str(episode["id"])
    return {
        "position": position,
        "episode_id": video_id,
        "title": str(episode.get("title") or video_id),
        "duration_seconds": int(episode.get("duration") or 0),
        "episode_url": _episode_url(video_id),
    }


def _load_existing_audit(
    output_file: Path,
) -> dict[str, CaptionAuditResult]:
    if not output_file.exists():
        return {}
    try:
        payload = json.loads(output_file.read_text(encoding="utf-8"))
        return {
            str(item["episode_id"]): CaptionAuditResult(**item)
            for item in payload.get("episodes", [])
            if item.get("episode_id")
        }
    except (json.JSONDecodeError, OSError, TypeError):
        return {}


def _english_languages(captions: dict[str, Any]) -> list[str]:
    return sorted(
        language
        for language in captions
        if language == "en" or language.startswith("en-")
    )


def _episode_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def _format_duration(total_seconds: int) -> str:
    hours, remainder = divmod(max(int(total_seconds), 0), 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)
