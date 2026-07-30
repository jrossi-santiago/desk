from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class CaptionEvent:
    start_ms: int
    end_ms: int
    text: str


@dataclass(frozen=True)
class TranscriptChunk:
    start_seconds: int
    end_seconds: int
    text: str


def parse_json3(path: Path) -> list[CaptionEvent]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    events: list[CaptionEvent] = []

    for event in payload.get("events", []):
        segments = event.get("segs")
        if not segments:
            continue

        text = "".join(segment.get("utf8", "") for segment in segments)
        text = _normalize_caption_text(text)
        if not text:
            continue

        start_ms = int(event.get("tStartMs", 0))
        duration_ms = max(int(event.get("dDurationMs", 0)), 1)
        events.append(
            CaptionEvent(
                start_ms=start_ms,
                end_ms=start_ms + duration_ms,
                text=text,
            )
        )

    return events


def chunk_events(
    events: Iterable[CaptionEvent], *, chunk_seconds: int = 90
) -> list[TranscriptChunk]:
    if chunk_seconds < 15:
        raise ValueError("chunk_seconds must be at least 15")

    buckets: dict[int, list[CaptionEvent]] = {}
    for event in events:
        bucket = (event.start_ms // 1000) // chunk_seconds
        buckets.setdefault(bucket, []).append(event)

    chunks: list[TranscriptChunk] = []
    for bucket in sorted(buckets):
        bucket_events = buckets[bucket]
        start_seconds = bucket * chunk_seconds
        end_seconds = max(event.end_ms for event in bucket_events) // 1000
        text = _join_phrases(event.text for event in bucket_events)
        if text:
            chunks.append(
                TranscriptChunk(
                    start_seconds=start_seconds,
                    end_seconds=end_seconds,
                    text=text,
                )
            )
    return chunks


def episode_metadata(info: dict[str, Any], transcript_source: str) -> dict[str, Any]:
    video_id = str(info["id"])
    upload_date = str(info.get("upload_date") or "")
    published = (
        f"{upload_date[0:4]}-{upload_date[4:6]}-{upload_date[6:8]}"
        if len(upload_date) == 8
        else upload_date
    )
    return {
        "episode_id": video_id,
        "title": str(info.get("title") or video_id),
        "published": published,
        "duration_seconds": int(info.get("duration") or 0),
        "episode_url": f"https://www.youtube.com/watch?v={video_id}",
        "channel": str(info.get("channel") or "MoreMozi"),
        "channel_id": str(info.get("channel_id") or ""),
        "transcript_source": transcript_source,
    }


def render_episode(metadata: dict[str, Any], chunks: list[TranscriptChunk]) -> str:
    lines = _frontmatter(metadata)
    lines.extend(
        [
            "",
            f"# {metadata['title']}",
            "",
            f"Video: [{metadata['episode_url']}]({metadata['episode_url']})",
            f"Published: {metadata.get('published') or 'unknown'}",
            (
                "Transcript source: "
                f"{str(metadata['transcript_source']).replace('_', ' ')}"
            ),
            "",
            "> Captions may contain transcription errors. Verify important details "
            "against the linked video.",
        ]
    )
    for chunk in chunks:
        timestamp = format_timestamp(chunk.start_seconds)
        url = timestamp_url(metadata["episode_url"], chunk.start_seconds)
        lines.extend(["", f"## [{timestamp}]({url})", "", chunk.text])
    return "\n".join(lines).rstrip() + "\n"


def render_segment(metadata: dict[str, Any], chunk: TranscriptChunk) -> str:
    segment_metadata = {
        **metadata,
        "start_seconds": chunk.start_seconds,
        "end_seconds": chunk.end_seconds,
        "timestamp_url": timestamp_url(
            metadata["episode_url"], chunk.start_seconds
        ),
    }
    timestamp = format_timestamp(chunk.start_seconds)
    lines = _frontmatter(segment_metadata)
    lines.extend(
        [
            "",
            f"# {metadata['title']} — {timestamp}",
            "",
            chunk.text,
            "",
            f"Source: [{metadata['title']} at {timestamp}]"
            f"({segment_metadata['timestamp_url']})",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def parse_frontmatter(text: str) -> dict[str, Any]:
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---\n", 4)
    if end == -1:
        return {}

    metadata: dict[str, Any] = {}
    for line in text[4:end].splitlines():
        key, separator, value = line.partition(":")
        if not separator:
            continue
        raw = value.strip()
        try:
            metadata[key.strip()] = json.loads(raw)
        except json.JSONDecodeError:
            metadata[key.strip()] = raw
    return metadata


def format_timestamp(total_seconds: int) -> str:
    total_seconds = max(int(total_seconds), 0)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def timestamp_url(episode_url: str, start_seconds: int) -> str:
    separator = "&" if "?" in episode_url else "?"
    return f"{episode_url}{separator}t={max(int(start_seconds), 0)}s"


def _frontmatter(metadata: dict[str, Any]) -> list[str]:
    lines = ["---"]
    for key, value in metadata.items():
        lines.append(
            f"{key}: {json.dumps(value, ensure_ascii=False, separators=(',', ':'))}"
        )
    lines.append("---")
    return lines


def _normalize_caption_text(text: str) -> str:
    text = html.unescape(text)
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _join_phrases(phrases: Iterable[str]) -> str:
    text = " ".join(phrase.strip() for phrase in phrases if phrase.strip())
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    return re.sub(r"\s+", " ", text).strip()
