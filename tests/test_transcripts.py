import json
import sys
from types import SimpleNamespace
import pytest
from app.transcripts import transcribe


@pytest.fixture
def video(tmp_path):
    p = tmp_path / 'meeting.mp4'
    p.write_bytes(b'video')
    return p


@pytest.mark.parametrize('data', [
    [{'text': 'ok', 'start_ms': 1.5, 'end_ms': 4.6}],
    {'segments': [{'text': 'ok', 'start': .0015, 'end': .0046}]},
])
def test_json_time_units_round_to_milliseconds(video, data):
    video.with_suffix('.transcript.json').write_text(json.dumps(data))
    result = transcribe(video, video_root=video.parent)
    assert result == [{'text': 'ok', 'start_ms': 2, 'end_ms': 5, 'source': 'sidecar_json'}]


@pytest.mark.parametrize('data', [[], {}, [{'text': ''}], [{'text': 5}],
    [{'text': 'x', 'start': True, 'end': 2}], [{'text': 'x', 'start': 1}],
    [{'text': 'x', 'start': -1, 'end': 2}], [{'text': 'x', 'start': 2, 'end': 1}],
    [{'text': 'x', 'start': float('nan'), 'end': 2}],
    [{'text': 'x', 'start': 1.0001, 'end': 1.0002}]])
def test_invalid_segments_fail(video, data):
    video.with_suffix('.transcript.json').write_text(json.dumps(data))
    with pytest.raises(ValueError):
        transcribe(video, video_root=video.parent)


def test_sidecar_symlink_cannot_escape(video, tmp_path):
    root = tmp_path / 'root'
    root.mkdir()
    clip = root / 'clip.mp4'
    clip.write_bytes(b'video')
    outside = tmp_path / 'outside.json'
    outside.write_text('[{"text":"x"}]')
    clip.with_suffix('.transcript.json').symlink_to(outside)
    with pytest.raises(ValueError):
        transcribe(clip, video_root=root)


def test_whisper_requires_local_model(video):
    with pytest.raises(ValueError, match='本地模型'):
        transcribe(video, 'whisper', video_root=video.parent, model_path='small')


def test_whisper_uses_local_path_cpu_and_no_download(video, monkeypatch):
    model = video.parent / 'model.pt'
    model.write_bytes(b'model')
    calls = {}
    def load(path, device):
        calls.update(path=path, device=device)
        def convert(audio, fp16):
            calls.update(fp16=fp16)
            return {'segments': [{'text': 'spoken', 'start': 0, 'end': 1}]}
        return SimpleNamespace(transcribe=convert)
    monkeypatch.setitem(sys.modules, 'whisper', SimpleNamespace(load_model=load))
    monkeypatch.setattr('app.transcripts.subprocess.run', lambda *a, **k: None)
    result = transcribe(video, 'whisper', video_root=video.parent, model_path=model,
                        audio_path=video.parent / 'audio.wav')
    assert calls == {'path': str(model), 'device': 'cpu', 'fp16': False}
    assert result[0]['source'] == 'whisper'
