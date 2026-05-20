import pytest
import sys
import os

# Ensure the src directory is in the path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

from dmx_frame import DMX512Frame

def test_dmx_frame_serialization():
    # 构造一个 512 通道的 DMX 帧数据
    slots = bytes([i % 256 for i in range(512)])
    frame = DMX512Frame(start_code=0x00, data=slots)
    
    # 验证序列化
    serialized = frame.to_bytes()
    assert len(serialized) == 513
    assert serialized[0] == 0x00
    assert serialized[1:] == slots
    
    # 验证反序列化
    parsed = DMX512Frame.from_bytes(serialized)
    assert parsed.start_code == 0x00
    assert parsed.data == slots

def test_dmx_frame_invalid_data():
    with pytest.raises(ValueError):
        # Data exceeds 512 slots
        DMX512Frame(start_code=0x00, data=bytes([0]*513))

def test_dmx_frame_empty_parsing():
    with pytest.raises(ValueError):
        DMX512Frame.from_bytes(b"")
