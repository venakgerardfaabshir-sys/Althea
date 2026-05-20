import pytest
import sys
import os

# Ensure the src directory is in the path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

from dmx_frame import DMX512Frame
from sdmx_encoder import SDMXEncoder

def test_adaptive_compression_initial_iframe():
    encoder = SDMXEncoder()
    # 首帧发送（即使没有 force_keyframe，首帧也会因为与初始全零状态对比而根据变化决定，这里强制发送 I-Frame 以确保基准）
    frame = DMX512Frame(data=bytes([10]*512))
    compressed = encoder.encode(frame, force_keyframe=True)
    assert len(compressed) == 513
    assert (compressed[0] & 0x0F) == 0x01  # I-Frame
    assert compressed[1:] == bytes([10]*512)

def test_keepalive_mode():
    encoder = SDMXEncoder()
    # 建立首帧基准
    frame1 = DMX512Frame(data=bytes([0]*512))
    encoder.encode(frame1, force_keyframe=True)
    
    # 状态无变化，生成 Keepalive 帧
    frame2 = DMX512Frame(data=bytes([0]*512))
    compressed = encoder.encode(frame2)
    assert len(compressed) == 1
    assert (compressed[0] & 0x0F) == 0x05  # Keepalive
    # 验证序列号递增
    assert (compressed[0] >> 4) == 1  # 序列号递增为 1

def test_sparse_mode():
    encoder = SDMXEncoder()
    # 建立首帧基准
    frame1 = DMX512Frame(data=bytes([0]*512))
    encoder.encode(frame1, force_keyframe=True)
    
    # 改变少于 150 个通道（这里改变 2 个通道：通道 10 和通道 200）
    frame2_data = bytearray([0]*512)
    frame2_data[10] = 255
    frame2_data[200] = 128
    frame2 = DMX512Frame(data=bytes(frame2_data))
    
    compressed = encoder.encode(frame2)
    # P-Sparse 格式：Header(1) + Count(1) + 2 * [Idx(2) + Val(1)] = 8 字节
    assert len(compressed) == 8
    assert (compressed[0] & 0x0F) == 0x02  # P-Sparse
    assert compressed[1] == 2  # Changed count
    # 验证通道 10
    idx1 = (compressed[2] << 8) | compressed[3]
    val1 = compressed[4]
    assert idx1 == 10
    assert val1 == 255
    # 验证通道 200
    idx2 = (compressed[5] << 8) | compressed[6]
    val2 = compressed[7]
    assert idx2 == 200
    assert val2 == 128

def test_range_mode():
    encoder = SDMXEncoder()
    # 建立首帧基准
    frame1 = DMX512Frame(data=bytes([0]*512))
    encoder.encode(frame1, force_keyframe=True)
    
    # 改变连续区间（改变通道 10 到 39，共 30 个通道）
    frame2_data = bytearray([0]*512)
    for i in range(10, 40):
        frame2_data[i] = 100
    frame2 = DMX512Frame(data=bytes(frame2_data))
    
    compressed = encoder.encode(frame2)
    # P-Range 格式：Header(1) + Start(2) + Span(2) + Data(30) = 35 字节
    # 对比 P-Sparse：2 + 30 * 3 = 92 字节；P-Bitmap: 1 + 64 + 30 = 95 字节
    # 所以应该自适应选择 P-Range！
    assert (compressed[0] & 0x0F) == 0x04  # P-Range
    assert len(compressed) == 35
    start = (compressed[1] << 8) | compressed[2]
    span = (compressed[3] << 8) | compressed[4]
    assert start == 10
    assert span == 30
    assert compressed[5:] == bytes([100]*30)

def test_bitmap_mode():
    encoder = SDMXEncoder()
    # 建立首帧基准
    frame1 = DMX512Frame(data=bytes([0]*512))
    encoder.encode(frame1, force_keyframe=True)
    
    # 散点改变中等数量的通道（这里改变 25 个不相邻的通道）
    # 对比：
    # P-Sparse: 2 + 25 * 3 = 77 字节
    # P-Bitmap: 1 + 64 + 25 = 90 字节
    # 让我们改变 35 个通道：
    # P-Sparse: 2 + 35 * 3 = 107 字节
    # P-Bitmap: 1 + 64 + 35 = 100 字节
    # 所以应该自适应选择 P-Bitmap！
    frame2_data = bytearray([0]*512)
    changed_indices = [i * 12 for i in range(35)]  # 0, 12, 24, ...
    for idx in changed_indices:
        frame2_data[idx] = 150
    frame2 = DMX512Frame(data=bytes(frame2_data))
    
    compressed = encoder.encode(frame2)
    assert (compressed[0] & 0x0F) == 0x03  # P-Bitmap
    assert len(compressed) == 1 + 64 + 35
    # 验证位图
    bitmap = compressed[1:65]
    data_part = compressed[65:]
    assert len(data_part) == 35
    for idx in changed_indices:
        byte_idx = idx // 8
        bit_idx = idx % 8
        assert (bitmap[byte_idx] & (1 << bit_idx)) != 0
    assert data_part == bytes([150]*35)

def test_flicker_filtering():
    # 闪烁滤波阈值设为 1（过滤 <=1 的变化）
    encoder = SDMXEncoder(flicker_threshold=1)
    
    # 首帧建立基准
    frame1 = DMX512Frame(data=bytes([128]*512))
    encoder.encode(frame1, force_keyframe=True)
    
    # 产生微小抖动（+-1 变化）
    frame2_data = bytearray([128]*512)
    frame2_data[10] = 129
    frame2_data[50] = 127
    frame2 = DMX512Frame(data=bytes(frame2_data))
    
    compressed2 = encoder.encode(frame2)
    # 因为抖动被静默，应该生成 Keepalive 帧 (1 字节)
    assert len(compressed2) == 1
    assert (compressed2[0] & 0x0F) == 0x05
    
    # 产生明显变化（> 1 变化）
    frame3_data = bytearray([128]*512)
    frame3_data[10] = 130  # +2 变化
    frame3 = DMX512Frame(data=bytes(frame3_data))
    compressed3 = encoder.encode(frame3)
    # 应该识别到通道 10 改变，输出 P-Sparse 增量帧 (5 字节)
    # Header(1) + Count(1) + 1 * [Idx(2) + Val(1)] = 5 字节
    assert len(compressed3) == 5
    assert (compressed3[0] & 0x0F) == 0x02
