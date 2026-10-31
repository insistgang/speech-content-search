from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.media import probe_video, resolve_video_path


@pytest.fixture
def video_root(tmp_path: Path) -> Path:
    root = tmp_path / "library"
    root.mkdir()
    return root


def test_resolve_video_path_accepts_supported_file_inside_root(video_root: Path) -> None:
    video = video_root / "meeting.MP4"
    video.write_bytes(b"video")

    assert resolve_video_path("meeting.MP4", video_root) == video.resolve()


def test_resolve_video_path_rejects_traversal_and_unsupported_file(video_root: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"video")
    (video_root / "notes.txt").write_text("not a video", encoding="utf-8")

    with pytest.raises(ValueError):
        resolve_video_path("../outside.mp4", video_root)
    with pytest.raises(ValueError):
        resolve_video_path("notes.txt", video_root)


def test_resolve_video_path_rejects_directory_unless_allowed(video_root: Path) -> None:
    folder = video_root / "sessions"
    folder.mkdir()

    with pytest.raises(ValueError):
        resolve_video_path(folder, video_root)
    assert resolve_video_path(folder, video_root, allow_directory=True) == folder.resolve()


def test_resolve_video_path_rejects_symlink_that_escapes_root(video_root: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"video")
    link = video_root / "linked.mp4"
    try:
        link.symlink_to(outside)
    except (NotImplementedError, OSError) as error:
        pytest.skip(f"symlinks unavailable: {error}")

    with pytest.raises(ValueError):
        resolve_video_path(link, video_root)


def test_probe_video_uses_argument_list_and_returns_duration_size_and_format(
    video_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video = video_root / "clip.mkv"
    video.write_bytes(b"12345")
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def fake_run(*args: object, **kwargs: object) -> SimpleNamespace:
        calls.append((args, kwargs))
        return SimpleNamespace(stdout=json.dumps({"format": {"duration": "12.75", "format_name": "matroska,webm"}}))

    monkeypatch.setattr("app.media.subprocess.run", fake_run)

    result = probe_video(video, command="probe-tool")

    assert result == {"duration_seconds": 12.75, "size_bytes": 5, "format": "matroska,webm"}
    args, kwargs = calls[0]
    command_args = args[0]
    assert isinstance(command_args, list)
    assert command_args[0] == "probe-tool"
    assert str(video) in command_args
    assert kwargs.get("shell", False) is False
    assert isinstance(kwargs.get("timeout"), (int, float))
    assert kwargs.get("timeout", 0) > 0
    assert kwargs.get("check") is True


@pytest.mark.parametrize(
    "stdout",
    ["not json", "{}", '{"format":{"duration":"nan","format_name":"mp4"}}'],
)
def test_probe_video_rejects_unusable_ffprobe_output(
    video_root: Path, monkeypatch: pytest.MonkeyPatch, stdout: str
) -> None:
    video = video_root / "clip.mp4"
    video.write_bytes(b"video")
    monkeypatch.setattr("app.media.subprocess.run", lambda *args, **kwargs: SimpleNamespace(stdout=stdout))

    with pytest.raises(ValueError):
        probe_video(video)


def test_probe_video_converts_missing_program_to_value_error(video_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    video = video_root / "clip.mp4"
    video.write_bytes(b"video")

    def missing_program(*args: object, **kwargs: object) -> None:
        raise FileNotFoundError("ffprobe missing")

    monkeypatch.setattr("app.media.subprocess.run", missing_program)

    with pytest.raises(ValueError, match="ffprobe"):
        probe_video(video)
