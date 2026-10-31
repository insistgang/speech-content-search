from contextlib import asynccontextmanager
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Literal
import json
import os
import sqlite3
import unicodedata
import uuid

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from .db import Database
from .media import probe_video, resolve_video_path, VIDEO_SUFFIXES
from .transcripts import transcribe

ROOT = Path(__file__).resolve().parents[1]


def now():
    return datetime.now(timezone.utc).isoformat()


def normalize(text):
    return ' '.join(unicodedata.normalize('NFKC', text).casefold().split())


class ImportRequest(BaseModel):
    path: str = Field(min_length=1, max_length=2048)
    provider: Literal['sidecar', 'whisper'] = 'sidecar'
    recursive: bool = False


class RetryRequest(BaseModel):
    provider: Literal['sidecar', 'whisper'] = 'sidecar'


class SearchRequest(BaseModel):
    query: str = Field(default='', max_length=200)
    mode: Literal['exact', 'fuzzy'] = 'exact'
    limit: int = Field(default=30, ge=1, le=100)
    keyword_set_id: str | None = None


class KeywordsRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    terms: list[str] = Field(min_length=1, max_length=100)


def create_app(video_root=None, runtime=None):
    video_root = Path(video_root or os.environ.get('VIDEO_ROOT', ROOT / 'library')).resolve()
    runtime = Path(runtime or os.environ.get('RUNTIME_DIR', ROOT / 'runtime')).resolve()
    video_root.mkdir(parents=True, exist_ok=True)
    runtime.mkdir(parents=True, exist_ok=True)
    db = Database(runtime / 'app.db')

    @asynccontextmanager
    async def lifespan(application):
        with db.connection() as connection:
            connection.execute("UPDATE tasks SET status='failed', error_message='处理进程中断，请重试', updated_at=? WHERE status IN ('pending','running')", (now(),))
            connection.execute("UPDATE videos SET status='failed', error_message='处理进程中断，请重试' WHERE status IN ('pending','processing')")
        yield

    application = FastAPI(title='语音内容智能检索系统', version='1.0.0', lifespan=lifespan)
    application.state.db = db
    application.state.runtime = runtime
    web = ROOT / 'web'
    application.mount('/static', StaticFiles(directory=web), name='static')

    def get_video(identifier):
        rows = db.query('SELECT * FROM videos WHERE id=?', (identifier,))
        if not rows:
            raise HTTPException(404, '视频不存在')
        return rows[0]

    def process(video_id, task_id, provider):
        try:
            video = get_video(video_id)
            path = resolve_video_path(video['path'], video_root)
            with db.connection() as connection:
                connection.execute("UPDATE videos SET status='processing', error_message=NULL WHERE id=?", (video_id,))
                connection.execute("UPDATE tasks SET status='running', progress=10, updated_at=? WHERE id=?", (now(), task_id))
            metadata = probe_video(path)
            segments = transcribe(path, provider, video_root=video_root,
                                  model_path=os.environ.get('WHISPER_MODEL_PATH'),
                                  audio_path=runtime / 'audio' / f'{video_id}.wav')
            for segment in segments:
                if segment['end_ms'] is not None and segment['end_ms'] > metadata['duration_seconds'] * 1000 + 500:
                    raise ValueError('转写时间戳超过视频时长')
            with db.connection() as connection:
                connection.execute('DELETE FROM segments WHERE video_id=?', (video_id,))
                connection.executemany('INSERT INTO segments(video_id,start_ms,end_ms,text,source) VALUES(?,?,?,?,?)',
                                       [(video_id, row['start_ms'], row['end_ms'], row['text'], row['source']) for row in segments])
                connection.execute("UPDATE videos SET duration_seconds=?,size_bytes=?,format=?,status='ready',error_message=NULL WHERE id=?",
                                   (metadata['duration_seconds'], metadata['size_bytes'], metadata['format'], video_id))
                connection.execute("UPDATE tasks SET status='completed', progress=100, error_message=NULL, updated_at=? WHERE id=?", (now(), task_id))
        except Exception as error:
            message = str(error)[:500] or '处理失败'
            with db.connection() as connection:
                connection.execute("UPDATE videos SET status='failed',error_message=? WHERE id=?", (message, video_id))
                connection.execute("UPDATE tasks SET status='failed',error_message=?,updated_at=? WHERE id=?", (message, now(), task_id))

    def schedule(path, provider, background):
        existing = db.query('SELECT * FROM videos WHERE path=?', (str(path),))
        if existing:
            return {'video': existing[0], 'task': None, 'duplicate': True}
        video_id, task_id, timestamp = str(uuid.uuid4()), str(uuid.uuid4()), now()
        try:
            with db.connection() as connection:
                connection.execute("INSERT INTO videos(id,file_name,path,status,created_at) VALUES(?,?,?,'pending',?)", (video_id, path.name, str(path), timestamp))
                connection.execute("INSERT INTO tasks VALUES(?,?,'pending',0,NULL,?,?)", (task_id, video_id, timestamp, timestamp))
        except sqlite3.IntegrityError:
            return {'video': db.query('SELECT * FROM videos WHERE path=?', (str(path),))[0], 'task': None, 'duplicate': True}
        background.add_task(process, video_id, task_id, provider)
        return {'video': get_video(video_id), 'task': db.query('SELECT * FROM tasks WHERE id=?', (task_id,))[0], 'duplicate': False}

    @application.get('/')
    def index():
        return FileResponse(web / 'index.html')

    @application.get('/api/health')
    def health():
        return {'status': 'ok', 'version': '1.0.0'}

    @application.get('/api/videos')
    def videos():
        return {'videos': db.query('SELECT * FROM videos ORDER BY created_at DESC')}

    @application.post('/api/videos/import-file', status_code=202)
    def import_file(request: ImportRequest, background_tasks: BackgroundTasks):
        try:
            path = resolve_video_path(request.path, video_root)
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        return schedule(path, request.provider, background_tasks)

    @application.post('/api/videos/import-folder', status_code=202)
    def import_folder(request: ImportRequest, background_tasks: BackgroundTasks):
        try:
            folder = resolve_video_path(request.path, video_root, allow_directory=True)
            if not folder.is_dir():
                raise ValueError('需要目录路径')
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        imported, errors = [], []
        paths = folder.rglob('*') if request.recursive else folder.iterdir()
        for candidate in sorted(paths):
            if not candidate.is_file() or candidate.suffix.lower() not in VIDEO_SUFFIXES:
                continue
            if len(imported) >= 100:
                errors.append({'path': str(folder), 'message': '单批最多 100 个视频，请分批导入'})
                break
            try:
                imported.append(schedule(resolve_video_path(candidate, video_root), request.provider, background_tasks))
            except ValueError as error:
                errors.append({'path': str(candidate), 'message': str(error)})
        return {'imported': imported, 'errors': errors}

    @application.post('/api/videos/{identifier}/retry', status_code=202)
    def retry(identifier: str, request: RetryRequest, background_tasks: BackgroundTasks):
        video = get_video(identifier)
        task_id, timestamp = str(uuid.uuid4()), now()
        with db.connection() as connection:
            updated = connection.execute("UPDATE videos SET status='pending',error_message=NULL WHERE id=? AND status NOT IN ('pending','processing')", (identifier,))
            if updated.rowcount == 0:
                raise HTTPException(409, '任务正在处理')
            connection.execute("INSERT INTO tasks VALUES(?,?,'pending',0,NULL,?,?)", (task_id, identifier, timestamp, timestamp))
        background_tasks.add_task(process, identifier, task_id, request.provider)
        return {'video': get_video(identifier), 'task': db.query('SELECT * FROM tasks WHERE id=?', (task_id,))[0]}

    @application.delete('/api/videos/{identifier}')
    def delete_video(identifier: str):
        get_video(identifier)
        with db.connection() as connection:
            deleted = connection.execute("DELETE FROM videos WHERE id=? AND status NOT IN ('pending','processing')", (identifier,))
            if not deleted.rowcount:
                raise HTTPException(409, '处理完成后才能移除记录')
        cache = runtime / 'audio' / f'{identifier}.wav'
        if cache.is_file():
            cache.unlink()
        return {'deleted': True}

    @application.get('/api/videos/{identifier}/file')
    def video_file(identifier: str):
        try:
            path = resolve_video_path(get_video(identifier)['path'], video_root)
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        return FileResponse(path)

    @application.get('/api/tasks')
    def tasks():
        return {'tasks': db.query('SELECT * FROM tasks ORDER BY created_at DESC')}

    @application.get('/api/keywords')
    def keywords():
        return {'sets': [dict(row, terms=json.loads(row['terms'])) for row in db.query('SELECT * FROM keyword_sets ORDER BY name')]}

    @application.post('/api/keywords', status_code=201)
    def add_keywords(request: KeywordsRequest):
        terms = list(dict.fromkeys(term.strip() for term in request.terms if term.strip()))
        if not request.name.strip() or not terms or any(len(term) > 200 for term in terms):
            raise HTTPException(400, '需要有效词库名称与查询词')
        identifier = str(uuid.uuid4())
        with db.connection() as connection:
            connection.execute('INSERT INTO keyword_sets VALUES(?,?,?)', (identifier, request.name.strip(), json.dumps(terms, ensure_ascii=False)))
        return {'id': identifier, 'name': request.name.strip(), 'terms': terms}

    @application.delete('/api/keywords/{identifier}')
    def delete_keywords(identifier: str):
        with db.connection() as connection:
            result = connection.execute('DELETE FROM keyword_sets WHERE id=?', (identifier,))
            if not result.rowcount:
                raise HTTPException(404, '词库不存在')
        return {'deleted': True}

    @application.post('/api/search')
    def search(request: SearchRequest):
        queries = [normalize(request.query)] if request.query.strip() else []
        if request.keyword_set_id:
            rows = db.query('SELECT terms FROM keyword_sets WHERE id=?', (request.keyword_set_id,))
            if not rows:
                raise HTTPException(404, '词库不存在')
            queries += [normalize(term) for term in json.loads(rows[0]['terms'])]
        queries = list(dict.fromkeys(queries))
        if not queries:
            raise HTTPException(400, '请输入查询词或选择词库')
        results = []
        for row in db.query('SELECT s.*,v.file_name FROM segments s JOIN videos v ON v.id=s.video_id'):
            content = normalize(row['text'])
            best, match_type = 0.0, 'exact'
            for query in queries:
                if query in content:
                    best, match_type = 100.0, 'exact'
                    break
                if request.mode == 'fuzzy' and len(query) > 1:
                    windows = [content[i:i + len(query)] for i in range(max(1, len(content) - len(query) + 1))]
                    score = max(SequenceMatcher(None, query, window).ratio() * 100 for window in windows)
                    if score >= 75 and score > best:
                        best, match_type = score, 'fuzzy'
            if best:
                results.append({key: row[key] for key in ['video_id', 'file_name', 'text', 'start_ms', 'end_ms']} | {
                    'score': round(best, 1), 'match_type': match_type,
                    'timestamp_available': row['start_ms'] is not None and row['end_ms'] is not None})
        results.sort(key=lambda row: (-row['score'], row['file_name'], row['start_ms'] or 0))
        return {'query': request.query, 'count': len(results), 'results': results[:request.limit]}

    return application


app = create_app()
