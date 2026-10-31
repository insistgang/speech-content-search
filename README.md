# 语音内容智能检索系统 V1.0

按用户确认于 2026-10-03 独立重建。FastAPI、SQLite 和原生网页提供视频/文件夹导入、转写任务、失败重试、精确与模糊检索、词库管理和视频播放定位。

## 启动与测试

需要 Python 3.12、ffmpeg 和 ffprobe；后两者须在 PATH 中可用。

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8007
.venv/bin/python -m pytest -q
node --test tests/frontend.test.cjs
```

访问 `http://127.0.0.1:8007`，API 合同见 [SPEC.md](SPEC.md) 和 `/docs`。默认只允许导入 library 内的文件，填写 `操作演示.mp4` 这样的相对路径，或目录内的绝对路径。VIDEO_ROOT 可指定允许目录，RUNTIME_DIR 可指定数据库和生成音频目录。

## 转写与演示

默认读取同名 sidecar：`视频名.transcript.json` 或 `视频名.transcript.txt`。JSON 示例：

```json
{"segments":[{"start_ms":3000,"end_ms":7000,"text":"在此检索已有转写内容"}]}
```

TXT 每个非空行形成一条无时间戳的片段，因此从头播放。文件与 sidecar 的真实路径都必须在允许目录中；非法时间、空文本和越界路径明确失败。

可选 Whisper 需另行安装 openai-whisper，设置 WHISPER_MODEL_PATH 指向本机已有模型文件；本工程不会下载模型。适配器使用 CPU 和 fp16=False。本次验证了调用契约，尚未实际加载 Whisper 模型。

`library/操作演示.mp4` 是本次生成的 8 秒无声测试视频；配套 JSON 是人工编写的演示转写。它证明 sidecar 导入、检索和定位流程，不能作为自动语音识别效果的证据。浏览器已验证命中 3–7 秒片段，并实际定位到 3 秒。

## 验证和边界

35 项 Python 测试与 2 项网页接口合同测试通过，覆盖媒体探针、目录与符号链接、时间戳、事务更新、失败重试、任务重启、词库、检索和原视频保护。320px 视口无横向溢出。

本版本用于本地单用户处理。任务在同一服务进程中执行；重启后未完成任务标为失败并允许重试。删除操作只删除索引和生成音频，不删除原视频。未实现分布式队列、声纹分离、向量语义搜索或 Kimi 重排。

来源核对用 video-speech-search 仓库是画面检索工程，未作为本项目源码。新项目日期、实际作者、合法权利来源和协议适用版本须依据真实事实确认。
