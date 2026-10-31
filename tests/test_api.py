import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from app.main import create_app


@pytest.fixture
def setup(tmp_path, monkeypatch):
    root = tmp_path / 'library'
    root.mkdir()
    video = root / '会议.mp4'
    video.write_bytes(b'video')
    video.with_suffix('.transcript.json').write_text(json.dumps({'segments': [
        {'text': '部署系统出现错误', 'start': 1.2, 'end': 3.5},
        {'text': '系统已经恢复', 'start': 4, 'end': 6},
    ]}, ensure_ascii=False))
    monkeypatch.setattr('app.main.probe_video', lambda *a, **k: {
        'duration_seconds': 10.0, 'size_bytes': 5, 'format': 'mp4'})
    application = create_app(root, tmp_path / 'runtime')
    with TestClient(application) as client:
        yield client, root, video, application


def imported(client, video):
    result = client.post('/api/videos/import-file', json={'path': str(video)})
    assert result.status_code == 202
    return result.json()['video']['id']


def test_import_search_and_delete_preserve_original(setup):
    client, root, video, _ = setup
    identifier = imported(client, video)
    assert client.get('/api/videos').json()['videos'][0]['status'] == 'ready'
    response = client.post('/api/search', json={'query': '部署系统', 'mode': 'exact'})
    hit = response.json()['results'][0]
    assert hit['start_ms'] == 1200 and hit['end_ms'] == 3500
    assert hit['timestamp_available'] is True
    assert client.get(f'/api/videos/{identifier}/file').content == b'video'
    assert client.delete(f'/api/videos/{identifier}').status_code == 200
    assert video.exists()
    assert client.post('/api/search', json={'query': '部署'}).json()['count'] == 0


def test_path_escape_is_rejected(setup, tmp_path):
    client, _, _, _ = setup
    outside = tmp_path / 'escape.mp4'
    outside.write_bytes(b'video')
    assert client.post('/api/videos/import-file', json={'path': str(outside)}).status_code == 400


def test_duplicate_import_keeps_one_video(setup):
    client, _, video, _ = setup
    identifier = imported(client, video)
    again = client.post('/api/videos/import-file', json={'path': str(video)})
    assert again.json()['duplicate'] is True
    assert again.json()['video']['id'] == identifier
    assert len(client.get('/api/videos').json()['videos']) == 1


def test_failed_sidecar_can_be_retried(setup):
    client, _, video, _ = setup
    sidecar = video.with_suffix('.transcript.json')
    sidecar.write_text('[{"text":"bad","start":5,"end":1}]')
    identifier = imported(client, video)
    assert client.get('/api/tasks').json()['tasks'][0]['status'] == 'failed'
    sidecar.write_text('[{"text":"恢复成功","start":0,"end":1}]')
    response = client.post(f'/api/videos/{identifier}/retry', json={'provider': 'sidecar'})
    assert response.status_code == 202
    assert client.get('/api/videos').json()['videos'][0]['status'] == 'ready'


def test_plain_text_has_no_invented_timestamp(setup):
    client, _, video, _ = setup
    video.with_suffix('.transcript.json').unlink()
    video.with_suffix('.transcript.txt').write_text('没有时间戳的会议记录')
    imported(client, video)
    hit = client.post('/api/search', json={'query': '会议'}).json()['results'][0]
    assert hit['timestamp_available'] is False
    assert hit['start_ms'] is None and hit['end_ms'] is None


def test_percent_is_literal_and_fuzzy_recalls_typo(setup):
    client, _, video, _ = setup
    video.with_suffix('.transcript.json').write_text('[{"text":"deployment error happened","start":0,"end":1}]')
    imported(client, video)
    assert client.post('/api/search', json={'query': '%'}).json()['count'] == 0
    assert client.post('/api/search', json={'query': 'deploymnt error', 'mode': 'fuzzy'}).json()['count'] == 1


def test_keyword_set_queries_deduplicate(setup):
    client, _, video, _ = setup
    imported(client, video)
    result = client.post('/api/keywords', json={'name': '故障', 'terms': ['部署', '错误', '部署']})
    assert result.status_code == 201
    identifier = result.json()['id']
    search = client.post('/api/search', json={'query': '', 'keyword_set_id': identifier})
    assert search.json()['count'] == 1
    assert client.delete(f'/api/keywords/{identifier}').status_code == 200


def test_empty_query_and_invalid_limit_are_rejected(setup):
    client, *_ = setup
    assert client.post('/api/search', json={'query': ' '}).status_code == 400
    assert client.post('/api/search', json={'query': 'test', 'limit': 101}).status_code == 422


def test_home_assets_are_served_from_public_directory_only(setup):
    client, *_ = setup
    assert '/static/app.js' in client.get('/').text
    assert client.get('/static/app.js').status_code == 200
    assert client.get('/static/style.css').status_code == 200
    assert client.get('/static/../app/main.py').status_code == 404


def test_over_duration_transcript_fails(setup):
    client, _, video, _ = setup
    video.with_suffix('.transcript.json').write_text('[{"text":"too late","start":11,"end":12}]')
    imported(client, video)
    assert client.get('/api/videos').json()['videos'][0]['status'] == 'failed'


def test_restart_marks_unfinished_task_and_keeps_transcripts(setup):
    client, root, video, application = setup
    identifier = imported(client, video)
    with application.state.db.connection() as connection:
        connection.execute("UPDATE videos SET status='processing' WHERE id=?", (identifier,))
        connection.execute("UPDATE tasks SET status='running' WHERE video_id=?", (identifier,))
    restarted = create_app(root, application.state.runtime)
    with TestClient(restarted) as second:
        assert second.get('/api/tasks').json()['tasks'][0]['status'] == 'failed'
        assert second.post('/api/search', json={'query': '部署'}).json()['count'] == 1
