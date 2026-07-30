from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .captions import (
    chunk_events,
    episode_metadata,
    parse_json3,
    render_episode,
    render_segment,
)

DEFAULT_CHANNEL_URL = "https://www.youtube.com/@MoreMozi/videos"
YOUTUBE_EXTRACTOR_ARGS = (
    "youtube:player_client=web_embedded",
    "youtube:player_client=tv",
)


@dataclass(frozen=True)
class SyncResult:
    episode_id: str
    title: str
    status: str
    segment_count: int = 0
    error: str | None = None


def default_data_dir() -> Path:
    configured = os.environ.get("ASK_HORMOZI_DATA_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    config_path = Path.home() / ".config" / "ask-hormozi" / "config.json"
    if config_path.exists():
        try:
            payload = json.loads(config_path.read_text(encoding="utf-8"))
            data_dir = payload.get("data_dir")
            if data_dir:
                return Path(str(data_dir)).expanduser().resolve()
        except (json.JSONDecodeError, OSError):
            pass
    return Path.home() / ".local" / "share" / "ask-hormozi" / "data"


def list_episodes(
    channel_url: str = DEFAULT_CHANNEL_URL, *, limit: int | None = None
) -> list[dict[str, Any]]:
    command = [
        "yt-dlp",
        "--no-warnings",
        "--flat-playlist",
        "--dump-single-json",
        "--extractor-args",
        YOUTUBE_EXTRACTOR_ARGS[0],
    ]
    if limit:
        command.extend(["--playlist-end", str(limit)])
    command.append(channel_url)
    payload = json.loads(_run(command).stdout)
    return [
        entry
        for entry in payload.get("entries", [])
        if entry and entry.get("id")
    ]


def sync_channel(
    *,
    data_dir: Path,
    channel_url: str = DEFAULT_CHANNEL_URL,
    limit: int | None = None,
    jobs: int = 4,
    force: bool = False,
    chunk_seconds: int = 90,
    progress: Callable[[SyncResult, int, int], None] | None = None,
) -> list[SyncResult]:
    _require_executable("yt-dlp")
    data_dir = data_dir.expanduser().resolve()
    episodes = list_episodes(channel_url, limit=limit)
    total = len(episodes)
    results: list[SyncResult] = []

    with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        futures = {
            pool.submit(
                sync_episode,
                episode,
                data_dir=data_dir,
                force=force,
                chunk_seconds=chunk_seconds,
            ): episode
            for episode in episodes
        }
        for completed, future in enumerate(as_completed(futures), start=1):
            episode = futures[future]
            try:
                result = future.result()
            except Exception as exc:  # preserve per-episode progress
                result = SyncResult(
                    episode_id=str(episode["id"]),
                    title=str(episode.get("title") or episode["id"]),
                    status="failed",
                    error=str(exc),
                )
            results.append(result)
            if progress:
                progress(result, completed, total)

    results.sort(key=lambda result: result.episode_id)
    catalog = {
        "channel_url": channel_url,
        "episode_count": total,
        "transcribed_count": sum(
            result.status in {"created", "cached"} for result in results
        ),
        "missing_caption_count": sum(
            result.status == "missing_captions" for result in results
        ),
        "failed_count": sum(result.status == "failed" for result in results),
        "episodes": [result.__dict__ for result in results],
    }
    _write_text(
        data_dir / "transcript-manifest.json",
        json.dumps(catalog, indent=2, ensure_ascii=False) + "\n",
    )
    return results


def sync_episode(
    episode: dict[str, Any],
    *,
    data_dir: Path,
    force: bool = False,
    chunk_seconds: int = 90,
) -> SyncResult:
    video_id = str(episode["id"])
    transcript_path = data_dir / "transcripts" / f"{video_id}.md"
    metadata_path = data_dir / "metadata" / f"{video_id}.json"
    segment_dir = data_dir / "segments" / video_id.lower()

    if transcript_path.exists() and metadata_path.exists() and not force:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        return SyncResult(
            episode_id=video_id,
            title=str(metadata.get("title") or episode.get("title") or video_id),
            status="cached",
            segment_count=len(list(segment_dir.glob("*.md"))),
        )

    with tempfile.TemporaryDirectory(prefix=f"ask-hormozi-{video_id}-") as raw_dir:
        raw_path = Path(raw_dir)
        output_template = str(raw_path / "%(id)s.%(ext)s")
        base_command = [
            "yt-dlp",
            "--no-warnings",
            "--no-progress",
            "--skip-download",
            "--ignore-no-formats-error",
            "--write-info-json",
            "--write-subs",
            "--write-auto-subs",
            "--sub-langs",
            "en-orig,en",
            "--sub-format",
            "json3",
            "--output",
            output_template,
        ]
        last_error: subprocess.CalledProcessError | None = None
        info: dict[str, Any] | None = None
        caption_path: Path | None = None
        transcript_source = "unavailable"
        info_path = raw_path / f"{video_id}.info.json"
        for extractor_args in YOUTUBE_EXTRACTOR_ARGS:
            try:
                _run(
                    [
                        *base_command,
                        "--extractor-args",
                        extractor_args,
                        f"https://www.youtube.com/watch?v={video_id}",
                    ]
                )
            except subprocess.CalledProcessError as exc:
                last_error = exc
                continue
            if not info_path.exists():
                continue
            info = json.loads(info_path.read_text(encoding="utf-8"))
            caption_path, transcript_source = _select_caption(raw_path, info)
            if caption_path is not None:
                break

        if info is None:
            if last_error is not None:
                raise last_error
            raise RuntimeError("yt-dlp did not produce video metadata")
        if caption_path is None:
            return SyncResult(
                episode_id=video_id,
                title=str(info.get("title") or episode.get("title") or video_id),
                status="missing_captions",
                error="No English manual or automatic captions were available.",
            )

        chunks = chunk_events(
            parse_json3(caption_path), chunk_seconds=chunk_seconds
        )
        if not chunks:
            raise RuntimeError("English caption file contained no usable text")
        metadata = episode_metadata(info, transcript_source)

    if segment_dir.exists():
        shutil.rmtree(segment_dir)
    segment_dir.mkdir(parents=True, exist_ok=True)
    for chunk in chunks:
        filename = f"{chunk.start_seconds:06d}.md"
        _write_text(segment_dir / filename, render_segment(metadata, chunk))
    _write_text(transcript_path, render_episode(metadata, chunks))
    _write_text(
        metadata_path,
        json.dumps(metadata, indent=2, ensure_ascii=False) + "\n",
    )

    return SyncResult(
        episode_id=video_id,
        title=metadata["title"],
        status="created",
        segment_count=len(chunks),
    )


def _select_caption(
    raw_path: Path, info: dict[str, Any]
) -> tuple[Path | None, str]:
    video_id = str(info["id"])
    manual = info.get("subtitles") or {}
    automatic = info.get("automatic_captions") or {}
    preferences = [
        ("en", "manual_captions", manual),
        ("en-orig", "manual_captions", manual),
        ("en-orig", "automatic_captions", automatic),
        ("en", "automatic_captions", automatic),
    ]
    for language, source, available in preferences:
        candidate = raw_path / f"{video_id}.{language}.json3"
        if language in available and candidate.exists():
            return candidate, source
    for language, source in (
        ("en-orig", "automatic_captions"),
        ("en", "automatic_captions"),
    ):
        candidate = raw_path / f"{video_id}.{language}.json3"
        if candidate.exists():
            return candidate, source
    return None, "unavailable"


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
    )


def _require_executable(name: str) -> None:
    if shutil.which(name) is None:
        raise RuntimeError(
            f"{name} is required but was not found on PATH. "
            "Run ./setup.sh to install dependencies."
        )


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)
