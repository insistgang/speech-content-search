import json
import math
import subprocess
from pathlib import Path
from .media import resolve_video_path


def normalize_segments(items, source):
    if not isinstance(items, list) or not items:
        raise ValueError('转写必须含有效片段列表')
    segments = []
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get('text'), str) or not item['text'].strip():
            raise ValueError('片段缺少有效文本')
        if 'start_ms' in item or 'end_ms' in item:
            start, end, factor = item.get('start_ms'), item.get('end_ms'), 1
        else:
            start, end, factor = item.get('start'), item.get('end'), 1000
        if start is None and end is None:
            start_ms = end_ms = None
        else:
            if any(isinstance(value, bool) or not isinstance(value, (int, float))
                   or not math.isfinite(value) or value < 0 for value in [start, end]):
                raise ValueError('时间戳必须成对且为非负有限数值')
            start_ms, end_ms = round(start * factor), round(end * factor)
            if end_ms <= start_ms:
                raise ValueError('结束时间必须晚于开始时间')
        segments.append({'text': item['text'].strip(), 'start_ms': start_ms,
                         'end_ms': end_ms, 'source': source})
    return segments


def transcribe(video_path, provider='sidecar', *, video_root, model_path=None,
               audio_path=None, ffmpeg_command='ffmpeg'):
    video = resolve_video_path(video_path, video_root)
    if provider == 'sidecar':
        root = Path(video_root).resolve()
        for suffix in ['.transcript.json', '.transcript.txt']:
            candidate = video.with_suffix(suffix)
            if not candidate.exists():
                continue
            path = candidate.resolve()
            if not path.is_relative_to(root) or not path.is_file():
                raise ValueError('转写文件超出允许目录')
            if path.stat().st_size > 10_000_000:
                raise ValueError('转写文件超过 10 MB')
            try:
                raw = path.read_text(encoding='utf-8-sig')
                if suffix.endswith('.json'):
                    data = json.loads(raw)
                    return normalize_segments(data.get('segments') if isinstance(data, dict) else data, 'sidecar_json')
                return normalize_segments([{'text': line} for line in raw.splitlines() if line.strip()], 'sidecar_txt')
            except (OSError, UnicodeError, json.JSONDecodeError) as error:
                raise ValueError('转写文件无法读取') from error
        raise ValueError('未找到同名 .transcript.json 或 .transcript.txt 转写文件')
    if provider != 'whisper':
        raise ValueError('转写提供器无效')
    model = Path(model_path).resolve() if model_path else None
    if model is None or not model.is_file():
        raise ValueError('Whisper 需要已存在的本地模型文件，不会自动下载')
    if not audio_path or Path(audio_path).resolve() == video:
        raise ValueError('需要独立的音频缓存路径')
    try:
        import whisper
    except ImportError as error:
        raise ValueError('本地未安装可选 openai-whisper 依赖') from error
    audio = Path(audio_path)
    audio.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run([ffmpeg_command, '-nostdin', '-y', '-i', str(video), '-vn',
                        '-ar', '16000', '-ac', '1', str(audio)],
                       capture_output=True, check=True, timeout=180)
        engine = whisper.load_model(str(model), device='cpu')
        result = engine.transcribe(str(audio), fp16=False)
        return normalize_segments(result.get('segments'), 'whisper')
    except (OSError, subprocess.SubprocessError) as error:
        raise ValueError('ffmpeg 音频抽取失败') from error
