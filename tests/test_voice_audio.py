import array
import struct

import pytest
from PySide6.QtMultimedia import QAudioFormat

from deskcare.voice.audio import to_vosk_pcm16


def test_audio_converter_downsamples_stereo_int16_to_mono_16khz():
    source = array.array("h", [1000, 1000, 1000, 1000, -1000, -1000, -1000, -1000])

    output = to_vosk_pcm16(source.tobytes(), 32000, 2, QAudioFormat.SampleFormat.Int16)

    result = array.array("h")
    result.frombytes(output)
    assert len(result) == 2
    assert result[0] == 1000
    assert result[1] == -1000


def test_audio_converter_handles_float_and_unsigned_8_bit_samples():
    floats = struct.pack("<4f", 0.0, 0.5, -0.5, 1.0)
    converted_float = to_vosk_pcm16(floats, 16000, 1, QAudioFormat.SampleFormat.Float)
    values = array.array("h")
    values.frombytes(converted_float)
    assert values.tolist() == [0, 16384, -16384, 32767]

    converted_u8 = to_vosk_pcm16(bytes([128, 255, 0, 128]), 16000, 1, QAudioFormat.SampleFormat.UInt8)
    values = array.array("h")
    values.frombytes(converted_u8)
    assert values.tolist() == [0, 32512, -32768, 0]


def test_audio_converter_rejects_unsupported_input_format():
    with pytest.raises(ValueError, match="暂不支持"):
        to_vosk_pcm16(b"\x00\x00", 4000, 1, QAudioFormat.SampleFormat.Int16)
