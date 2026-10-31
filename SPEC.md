# 语音内容智能检索系统重建规格

## 目标与范围

用户已确认重建独立语音检索项目，并重新生成材料。采用本地网页、Python 3.12、FastAPI 和 SQLite，导入配置目录内的视频，接入 sidecar 或可选本地 Whisper 转写，按关键词/词库检索文本，显示文件、片段及真实可用的时间戳。

本期实现本地视频和文件夹导入、持久任务记录、失败重试、视频列表/删除、精确和模糊检索、词库维护、视频播放定位。没有声纹分离、VAD 专项处理、波形图、向量索引、Kimi 重排和医疗/性能量化承诺。

## 结构与命令

- `app/`：配置、数据库、媒体探针、转写提供器、检索和 API。
- `web/`：静态网页，API 与媒体都同源。
- `tests/`：临时 SQLite、临时视频/sidecar、API 和边界回归。
- `library/`：默认允许导入目录；`runtime/`：数据库及生成音频。
- 安装：`python3.12 -m venv .venv`；`.venv/bin/python -m pip install -r requirements.txt`。
- 启动：`.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8007`。
- 测试：`.venv/bin/python -m pytest -q`。

## 数据模型与状态

视频字段：`id`、`file_name`、`path`、`duration_seconds`、`status`、`error_message`。视频状态为 `pending/processing/ready/failed`。

任务字段：`id`、`video_id`、`status`、`progress`、`error_message`、`created_at`、`updated_at`。任务状态为 `pending/running/completed/failed`；重启时未完成任务标为失败并允许重试，不伪装为完成。

片段字段：`video_id`、`start_ms`、`end_ms`、`text`、`source`。TXT 未提供时间时起止为 null，结果 `timestamp_available=false`。

JSON sidecar 文件名为 `video.transcript.json`，支持片段数组或 `{"segments":[...]}`，片段含 `text` 与成对的 `start_ms/end_ms`，或以秒表示的 `start/end`。TXT sidecar 为 `video.transcript.txt`，逐个非空行形成没有时间戳的片段。

## API 合同

| 方法 | 路径 | 输入与输出 |
|---|---|---|
| GET | `/api/health` | `{"status":"ok","version":"1.0.0"}` |
| GET | `/api/videos` | `{"videos":[视频对象]}` |
| POST | `/api/videos/import-file` | `{path,provider:"sidecar"或"whisper"}`；202 `{video,task,duplicate:false}`；重复导入返回同一视频 |
| POST | `/api/videos/import-folder` | `{path,provider,recursive:false}`；`{imported,errors}` |
| POST | `/api/videos/{id}/retry` | `{provider}`；202 `{video,task}`，正在处理时 409 |
| DELETE | `/api/videos/{id}` | `{deleted:true}`；不得删除原视频 |
| GET | `/api/videos/{id}/file` | 返回原视频媒体内容，并再次验证目录范围 |
| GET | `/api/tasks` | `{"tasks":[任务对象]}` |
| POST | `/api/search` | `{query,mode:"exact"或"fuzzy",limit:30,keyword_set_id:null}` |
| GET | `/api/keywords` | `{"sets":[{id,name,terms:[...]}]}` |
| POST | `/api/keywords` | `{name,terms:[...]}`；201 词库对象 |
| DELETE | `/api/keywords/{id}` | `{deleted:true}` |

检索输出：`{query,count,results:[{video_id,file_name,text,start_ms,end_ms,score,match_type,timestamp_available}]}`。查询和片段按 Unicode NFKC 与大小写归一化；精确模式不把 `%`、`_` 当 SQL 通配符；模糊模式使用文本窗口相似度，并关闭单字符模糊扩展。词库可作为多个查询词的集合，按片段去重。limit 为 1–100，文本查询最长 200 字，没有查询且未选择词库时明确报错。

## 失败与边界

- 文件不存在、目录越界、非支持的视频类型、无有效转写、非法时间区间、模型未配置必须显式失败。
- 输入目录默认只允许工程 `library/`；只监听 127.0.0.1。
- ffmpeg/ffprobe 用参数列表调用，设置超时；不得 `shell=True`。
- 模型安装、模型下载、外部 API、生产数据和对外部署不属于自动执行范围。
- 任务保留错误与进度；重试生成新任务；数据库片段在完整校验后更新。

## 工作拆分与验收

### 媒体与转写模块接口

- `app.media.resolve_video_path(value, video_root, allow_directory=False) -> Path`：真实路径必须在目录内，存在，类型正确；视频后缀 mp4/mov/mkv/avi/webm，错误抛 ValueError。
- `app.media.probe_video(path, command="ffprobe") -> dict`：返回 duration_seconds、size_bytes、format；参数列表执行，有超时，解析失败抛 ValueError。
- `app.transcripts.transcribe(video_path, provider="sidecar", *, video_root, model_path=None, audio_path=None, ffmpeg_command="ffmpeg") -> list[dict]`：返回 start_ms/end_ms/text/source 标准片段；sidecar JSON/TXT 也必须真实位于目录内；JSON 时间成对、有限、非负且起止递增；TXT 没有时间戳。
- Whisper 提供器先验证本地模型文件和依赖，再写入 app 提供的独立 audio_path，以 cpu/fp16=False 处理，不下载模型，不在模型缺失时假成功。
- API 流水线另校验片段时间不能明显超过视频时长，再以事务替换片段。

1. 导入/转写/任务：配置与数据库→媒体/sidecar→API；验收临时视频导入、准确片段落库、错误状态、路径守卫。
2. 检索/词库：精确、模糊、无时间戳、词库、去重；验收可复现查询与字段。
3. 前端：依据以上合同实现三个文件，其他 Agent 不改后端；验收真实列表、错误、播放定位、320px 无横向溢出。
4. 整合：跑 API 测试、浏览器流程和截图；从实际源码生成源程序、说明书和申请信息。

源码与材料不得继续采用旧工程的 4318 行、31 文件或历史完成日期；新总量由生成器统计，新日期由本次验收记录核对。
