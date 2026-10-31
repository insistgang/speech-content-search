from pathlib import Path
import json
import math
import subprocess

VIDEO_SUFFIXES = {'.mp4', '.mov', '.mkv', '.avi', '.webm'}


def resolve_video_path(value, video_root: Path, allow_directory=False) -> Path:
    root = Path(video_root).resolve()
    candidate = Path(value)
    path = (candidate if candidate.is_absolute() else root / candidate).resolve()
    if not path.is_relative_to(root):
        raise ValueError('文件路径不在允许的视频目录内')
    if not path.exists():
        raise ValueError('文件或目录不存在')
    if allow_directory and path.is_dir():
        return path
    if not path.is_file() or path.suffix.lower() not in VIDEO_SUFFIXES:
        raise ValueError('需要支持的视频文件 mp4/mov/mkv/avi/webm')
    return path


def probe_video(path: Path, command='ffprobe') -> dict:
    try:
        result = subprocess.run([
            command, '-v', 'error', '-show_format', '-of', 'json', str(path)
        ], capture_output=True, text=True, check=True, timeout=30)
        value = json.loads(result.stdout)['format']
        duration = float(value['duration'])
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError('invalid duration')
        return {'duration_seconds': duration, 'size_bytes': path.stat().st_size,
                'format': str(value['format_name'])}
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError) as error:
        raise ValueError('ffprobe 无法读取有效的视频元数据') from error
