import pytest
import sys
import os

# Ensure the src directory is in the path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

from dmx_frame import DMX512Frame
from sdmx_encoder import SDMXEncoder
from sdmx_decoder import SDMXDecoder

def test_compress_decompress_cycle():
    encoder = SDMXEncoder()
    decoder = SDMXDecoder()
    
    # 模拟 10 帧随机变化
    import random
    random.seed(42)
    
    current_slots = bytearray([0]*512)
    for frame_idx in range(10):
        # 模拟部分灯光变化
        for _ in range(random.randint(1, 5)):
            current_slots[random.randint(0, 511)] = random.randint(0, 255)
            
        original_frame = DMX512Frame(data=bytes(current_slots))
        
        # 编码（首帧强制发送 I-Frame）
        compressed = encoder.encode(original_frame, force_keyframe=(frame_idx == 0))
        
        # 解码
        reconstructed = decoder.decode(compressed)
        
        # 验证解码后的状态完全吻合编码器的最终状态（考虑到闪烁滤波）
        assert reconstructed.data == encoder.last_state

def test_decoder_sync_loss_on_sequence_gap():
    encoder = SDMXEncoder()
    decoder = SDMXDecoder()
    
    # 1. 建立初始同步 (I-Frame)
    frame1 = DMX512Frame(data=bytes([10]*512))
    compressed1 = encoder.encode(frame1, force_keyframe=True)
    decoder.decode(compressed1)
    assert not decoder.sync_lost
    
    # 2. 正常增量帧 1 (seq=1)
    frame2_data = bytearray([10]*512)
    frame2_data[50] = 100
    frame2 = DMX512Frame(data=bytes(frame2_data))
    compressed2 = encoder.encode(frame2)
    decoder.decode(compressed2)
    assert decoder.state[50] == 100
    assert not decoder.sync_lost
    
    # 3. 模拟丢包：跳过 seq=2 帧，发送 seq=3 帧
    # 我们调用 encoder 产生两帧，但只把第二帧给 decoder
    frame3_data = bytearray(frame2_data)
    frame3_data[60] = 150
    frame3 = DMX512Frame(data=bytes(frame3_data))
    compressed3 = encoder.encode(frame3) # seq = 2
    
    frame4_data = bytearray(frame3_data)
    frame4_data[70] = 200
    frame4 = DMX512Frame(data=bytes(frame4_data))
    compressed4 = encoder.encode(frame4) # seq = 3
    
    # decoder 直接收到 seq=3，跳过了 seq=2，应触发同步丢失
    reconstructed = decoder.decode(compressed4)
    assert decoder.sync_lost
    # 丢失同步时，解码结果应当拒绝接受增量更新，维持前一个安全同步状态的值，并且可以通过 decoder 实例查询到同步丢失
    assert decoder.state[70] != 200  # 拒绝更新增量
    
    # 4. 再次收到 I-Frame，恢复同步
    frame5 = DMX512Frame(data=bytes([50]*512))
    compressed5 = encoder.encode(frame5, force_keyframe=True)
    decoder.decode(compressed5)
    assert not decoder.sync_lost
    assert decoder.state == bytes([50]*512)
