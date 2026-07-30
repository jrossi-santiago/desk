from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from . import __version__
from .catalog import audit_caption_coverage, build_catalog
from .ingest import DEFAULT_CHANNEL_URL, SyncResult, default_data_dir, sync_channel
from .qmd_index import index_corpus, render_markdown_results, search_corpus


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ask-hormozi",
        description=(
            "Build and search a local, cited index of MoreMozi."
        ),
    )
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    sync = subparsers.add_parser(
        "sync", help="Download metadata/captions and build local transcripts."
    )
    sync.add_argument("--channel", default=DEFAULT_CHANNEL_URL)
    sync.add_argument("--data-dir", type=Path, default=default_data_dir())
    sync.add_argument("--limit", type=_positive_int)
    sync.add_argument("--jobs", type=_positive_int, default=4)
    sync.add_argument("--chunk-seconds", type=_positive_int, default=90)
    sync.add_argument("--force", action="store_true")

    catalog = subparsers.add_parser(
        "catalog", help="Build bundled video Markdown and YouTube metadata."
    )
    catalog.add_argument("--channel", default=DEFAULT_CHANNEL_URL)
    catalog.add_argument("--output-dir", type=Path, default=Path("corpus"))
    catalog.add_argument("--limit", type=_positive_int)

    audit = subparsers.add_parser(
        "audit-captions",
        help="Verify English caption availability without storing transcripts.",
    )
    audit.add_argument("--channel", default=DEFAULT_CHANNEL_URL)
    audit.add_argument(
        "--output-file",
        type=Path,
        default=Path("corpus") / "caption-coverage.json",
    )
    audit.add_argument("--limit", type=_positive_int)
    audit.add_argument("--jobs", type=_positive_int, default=4)
    audit.add_argument(
        "--delay",
        type=float,
        default=0,
        help="Seconds to wait before each video metadata request.",
    )
    audit.add_argument(
        "--no-resume",
        action="store_true",
        help="Recheck videos already verified in the output file.",
    )

    index = subparsers.add_parser(
        "index", help="Register the local transcript segments with QMD."
    )
    index.add_argument("--data-dir", type=Path, default=default_data_dir())
    index.add_argument("--collection", default="ask-hormozi")

    configure = subparsers.add_parser(
        "configure", help="Set the bundled corpus location used by default."
    )
    configure.add_argument("--data-dir", type=Path, required=True)

    search = subparsers.add_parser(
        "search", help="Search QMD and return cited transcript passages."
    )
    search.add_argument("query")
    search.add_argument("--data-dir", type=Path, default=default_data_dir())
    search.add_argument("--collection", default="ask-hormozi")
    search.add_argument("--limit", type=_positive_int, default=8)
    search.add_argument("--format", choices=("markdown", "json"), default="markdown")

    doctor = subparsers.add_parser(
        "doctor", help="Check required commands and local corpus status."
    )
    doctor.add_argument("--data-dir", type=Path, default=default_data_dir())
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "sync":
            _sync(args)
        elif args.command == "catalog":
            catalog = build_catalog(
                args.output_dir,
                channel_url=args.channel,
                limit=args.limit,
            )
            print(
                f"Wrote {catalog['episode_count']} video catalog entries "
                f"to {args.output_dir.expanduser().resolve()}."
            )
        elif args.command == "audit-captions":
            _audit_captions(args)
        elif args.command == "index":
            index_corpus(args.data_dir, collection=args.collection)
            print(
                f"Indexed {args.data_dir.expanduser().resolve()} "
                f"as QMD collection {args.collection}."
            )
        elif args.command == "configure":
            _configure(args.data_dir)
        elif args.command == "search":
            results = search_corpus(
                args.query,
                data_dir=args.data_dir,
                collection=args.collection,
                limit=args.limit,
            )
            if args.format == "json":
                print(
                    json.dumps(
                        {"query": args.query, "results": results},
                        indent=2,
                        ensure_ascii=False,
                    )
                )
            else:
                print(render_markdown_results(args.query, results), end="")
        elif args.command == "doctor":
            _doctor(args.data_dir)
    except (RuntimeError, OSError) as exc:
        parser.exit(1, f"error: {exc}\n")


def _sync(args: argparse.Namespace) -> None:
    def progress(result: SyncResult, completed: int, total: int) -> None:
        detail = f" ({result.error})" if result.error else ""
        print(
            f"[{completed:03d}/{total:03d}] {result.status:16} "
            f"{result.episode_id} {result.title}{detail}",
            flush=True,
        )

    results = sync_channel(
        data_dir=args.data_dir,
        channel_url=args.channel,
        limit=args.limit,
        jobs=args.jobs,
        force=args.force,
        chunk_seconds=args.chunk_seconds,
        progress=progress,
    )
    transcribed = sum(result.status in {"created", "cached"} for result in results)
    missing = sum(result.status == "missing_captions" for result in results)
    failed = sum(result.status == "failed" for result in results)
    print(
        f"Sync complete: {transcribed}/{len(results)} transcribed, "
        f"{missing} missing captions, {failed} failed."
    )
    if missing or failed:
        raise RuntimeError(
            "The corpus is incomplete. Inspect transcript-manifest.json and "
            "retry failed videos."
        )


def _audit_captions(args: argparse.Namespace) -> None:
    def progress(
        result: object, completed: int, total: int
    ) -> None:
        status = getattr(result, "status")
        episode_id = getattr(result, "episode_id")
        title = getattr(result, "title")
        print(
            f"[{completed:03d}/{total:03d}] {status:16} "
            f"{episode_id} {title}",
            flush=True,
        )

    payload = audit_caption_coverage(
        output_file=args.output_file,
        channel_url=args.channel,
        limit=args.limit,
        jobs=args.jobs,
        resume=not args.no_resume,
        request_delay=max(args.delay, 0),
        progress=progress,
    )
    print(
        f"Caption audit complete: {payload['captioned_count']}/"
        f"{payload['episode_count']} captioned, "
        f"{payload['missing_english_count']} missing English, "
        f"{payload['failed_count']} failed."
    )
    if payload["missing_english_count"] or payload["failed_count"]:
        raise RuntimeError(
            f"Caption coverage is incomplete. Inspect {args.output_file}."
        )


def _doctor(data_dir: Path) -> None:
    resolved = data_dir.expanduser().resolve()
    transcript_count = len(list((resolved / "transcripts").glob("*.md")))
    segment_count = len(list((resolved / "segments").glob("*/*.md")))
    catalog_count = len(list((resolved / "episodes").glob("*.md")))
    checks = {
        "python": sys.executable,
        "yt-dlp": shutil.which("yt-dlp"),
        "qmd": shutil.which("qmd"),
        "data_dir": str(resolved),
        "catalog_episodes": catalog_count,
        "transcripts": transcript_count,
        "segments": segment_count,
    }
    print(json.dumps(checks, indent=2))
    if not checks["qmd"]:
        raise RuntimeError("QMD is missing.")


def _configure(data_dir: Path) -> None:
    resolved = data_dir.expanduser().resolve()
    if not (resolved / "segments").exists() and not (
        resolved / "episodes"
    ).exists():
        raise RuntimeError(
            f"No bundled corpus found under {resolved}."
        )
    config_path = Path.home() / ".config" / "ask-hormozi" / "config.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps({"data_dir": str(resolved)}, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Configured bundled corpus: {resolved}")


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


if __name__ == "__main__":
    main()
