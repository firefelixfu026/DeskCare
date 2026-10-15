"""Convert common microphone PCM formats to Vosk's 16 kHz mono input."""

from __future__ import annotations

import array
import struct

from PySide6.QtMultimedia import QAudioFormat


def to_vosk_pcm16(pcm: bytes, sample_rate: int, channels: int, sample_format) -> bytes:
    """Convert supported Qt PCM formats without extra audio dependencies.

    Windows microphone devices commonly expose 44.1/48 kHz stereo or float
    audio rather than Vosk's required 16 kHz mono signed 16-bit PCM.
    """
    if sample_rate < 8000 or sample_rate > 192000 or not 1 <= channels <= 8:
        raise ValueError("麦克风音频格式暂不支持；请更换默认输入设备。")
    if sample_format == QAudioFormat.SampleFormat.UInt8:
        samples = [(value - 128) << 8 for value in pcm]
    elif sample_format == QAudioFormat.SampleFormat.Int16:
        usable = len(pcm) - len(pcm) % (2 * channels)
        values = array.array("h")
        values.frombytes(pcm[:usable])
        samples = values.tolist()
    elif sample_format == QAudioFormat.SampleFormat.Int32:
        usable = len(pcm) - len(pcm) % (4 * channels)
        values = array.array("i")
        values.frombytes(pcm[:usable])
        samples = [value >> 16 for value in values]
    elif sample_format == QAudioFormat.SampleFormat.Float:
        usable = len(pcm) - len(pcm) % (4 * channels)
        samples = [
            max(-32768, min(32767, round(value * 32767)))
            for (value,) in struct.iter_unpack("<f", pcm[:usable])
        ]
    else:
        raise ValueError("麦克风返回了不支持的音频格式；请检查 Windows 输入设备。")

    usable_samples = len(samples) - len(samples) % channels
    samples = samples[:usable_samples]
    if not samples:
        return b""
    if channels > 1:
        samples = [
            round(sum(samples[index:index + channels]) / channels)
            for index in range(0, len(samples), channels)
        ]
    output_count = max(1, round(len(samples) * 16000 / sample_rate))
    if sample_rate != 16000 and len(samples) > 1 and sample_rate % 16000 == 0:
        # A short box filter avoids aliasing for common 32/48 kHz devices.
        factor = sample_rate // 16000
        converted = []
        for start in range(0, len(samples), factor):
            window = samples[start:start + factor]
            if len(window) == factor:
                converted.append(round(sum(window) / factor))
        samples = converted or samples[:1]
    elif sample_rate != 16000 and len(samples) > 1:
        converted = []
        scale = sample_rate / 16000
        last = len(samples) - 1
        for index in range(output_count):
            position = min(index * scale, last)
            left = int(position)
            right = min(left + 1, last)
            fraction = position - left
            value = round(samples[left] * (1 - fraction) + samples[right] * fraction)
            converted.append(max(-32768, min(32767, value)))
        samples = converted
    output = array.array("h", (max(-32768, min(32767, value)) for value in samples))
    if output.itemsize != 2:
        raise RuntimeError("当前系统的 PCM 字节序不受支持。")
    if struct.pack("=H", 1) != struct.pack("<H", 1):
        output.byteswap()
    return output.tobytes()
