"""Optional Vosk adapter. Audio is accepted as an in-memory PCM buffer only."""

from __future__ import annotations

import json
from pathlib import Path


def transcribe_pcm(model_path: str, pcm16_mono: bytes, sample_rate: int = 16000) -> str:
    """Transcribe 16-bit, mono PCM locally; never writes audio or contacts a server."""
    path = Path(model_path).expanduser()
    if not path.is_dir():
        raise ValueError("请先选择已下载并解压的 Vosk 离线中文模型文件夹。")
    if not pcm16_mono:
        raise ValueError("没有录到语音，请按住按钮说话后再试。")
    try:
        from vosk import KaldiRecognizer, Model
    except ImportError as exc:
        raise RuntimeError("本地语音组件未安装。请在项目环境安装 DeskCare 的 voice 可选依赖。") from exc
    recognizer = KaldiRecognizer(Model(str(path)), sample_rate)
    recognizer.AcceptWaveform(pcm16_mono)
    result = json.loads(recognizer.FinalResult())
    return str(result.get("text", "")).strip()
