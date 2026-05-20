import pytest
import random
import time
import sys
import os

# Ensure the src directory is in the path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

from sdmx_encoder import SDMXEncoder
from sdmx_decoder import SDMXDecoder
from dmx_frame import DMX512Frame
from sdmx_interfaces import BandwidthController, DMXTimingRestorer

# 1. 验证闪烁滤波在噪声通道下的挽救效果（复现噪声瘫痪与滤波拯救边界）
def test_flicker_noise_reproduction():
    # 物理输入刷新帧率 F_in = 44.09 Hz
    F_in = 44.09
    state = bytearray([128]*512)
    
    # CASE A: 没有启用闪烁滤波 (flicker_threshold = 0)
    encoder_no_filter = SDMXEncoder(flicker_threshold=0)
    # 发送基准帧建立基线
    encoder_no_filter.encode(DMX512Frame(data=bytes(state)))
    
    # 产生 10 帧抖动
    total_bytes_no_filter = 0
    random.seed(42)
    for _ in range(10):
        # 10 个随机通道抖动 +-1
        jittered_state = bytearray(state)
        for idx in random.sample(range(512), 10):
            jittered_state[idx] += random.choice([-1, 1])
        frame = DMX512Frame(data=bytes(jittered_state))
        compressed = encoder_no_filter.encode(frame)
        total_bytes_no_filter += len(compressed)
        
    avg_bandwidth_no_filter = (total_bytes_no_filter / 10) * 8 * F_in / 1000.0
    print(f"\n[Noise Test] NO Filter: Avg Frame = {total_bytes_no_filter/10} Bytes, Bandwidth = {avg_bandwidth_no_filter:.2f} kbps")
    # 验证没有滤波时，2%噪声会导致带宽超过 10kbps 崩溃上限！
    assert avg_bandwidth_no_filter > 10.0
    
    # CASE B: 启用闪烁滤波 (flicker_threshold = 1)
    encoder_with_filter = SDMXEncoder(flicker_threshold=1)
    # 发送基准帧建立基线
    encoder_with_filter.encode(DMX512Frame(data=bytes(state)))
    
    total_bytes_with_filter = 0
    for _ in range(10):
        jittered_state = bytearray(state)
        for idx in random.sample(range(512), 10):
            jittered_state[idx] += random.choice([-1, 1])
        frame = DMX512Frame(data=bytes(jittered_state))
        compressed = encoder_with_filter.encode(frame)
        total_bytes_with_filter += len(compressed)
        
    avg_bandwidth_with_filter = (total_bytes_with_filter / 10) * 8 * F_in / 1000.0
    print(f"[Noise Test] WITH Filter: Avg Frame = {total_bytes_with_filter/10} Bytes, Bandwidth = {avg_bandwidth_with_filter:.2f} kbps")
    # 验证启用滤波后，噪声被完美静默，流量降至心跳级别 (< 0.5kbps)
    assert avg_bandwidth_with_filter < 0.5

# 2. 验证场景 A、B、C 的精确帧大小与带宽复现
def test_scenarios_bandwidth_and_frame_sizes():
    encoder = SDMXEncoder(flicker_threshold=1)
    F_in = 44.09
    
    # 场景 A: 少量摇头灯动作 (4通道变化，必须是非连续的，否则会优化成 P-Range!)
    state_a = bytearray([0]*512)
    # 首帧发送I-Frame建立基线
    encoder.encode(DMX512Frame(data=bytes(state_a)), force_keyframe=True)
    
    # 4 通道非连续变化 (10, 100, 200, 300)
    state_a[10] = 50
    state_a[100] = 60
    state_a[200] = 70
    state_a[300] = 80
    frame_a = DMX512Frame(data=bytes(state_a))
    compressed_a = encoder.encode(frame_a)
    
    # 验证 P-Sparse 格式：Header(1) + Count(1) + 4 * 3 = 14 字节
    assert compressed_a[0] & 0x0F == 0x02  # P-Sparse
    assert len(compressed_a) == 14
    bandwidth_a = 14 * 8 * F_in / 1000.0
    assert 4.8 < bandwidth_a < 5.1  # 4.94 kbps 左右
    
    # 场景 B: 连续流水灯 (24通道连续变化)
    state_b = bytearray(state_a)
    for i in range(50, 74):
        state_b[i] = 100
    frame_b = DMX512Frame(data=bytes(state_b))
    compressed_b = encoder.encode(frame_b)
    
    # 验证 P-Range 格式：Header(1) + Start(2) + Span(2) + 24 = 29 字节
    assert compressed_b[0] & 0x0F == 0x04  # P-Range
    assert len(compressed_b) == 29
    
    # 场景 C: 舞台场景宏切换 (180不相邻通道同时改变)
    state_c = bytearray(state_b)
    for i in range(80, 440, 2):  # 180个通道
        state_c[i] = 150
    frame_c = DMX512Frame(data=bytes(state_c))
    compressed_c = encoder.encode(frame_c)
    
    # 验证 P-Bitmap 格式：Header(1) + 64(位图) + 180 = 245 字节
    assert compressed_c[0] & 0x0F == 0x03  # P-Bitmap
    assert len(compressed_c) == 245

# 3. 验证最坏情况下的降频策略与接收端时延计算 (Temporal Decimation & Failsafe Simulation)
def test_worst_case_rate_limiting_and_delay():
    encoder = SDMXEncoder(flicker_threshold=1)
    limiter = BandwidthController(max_bytes_per_sec=1250)  # 10kbps 强限速
    restorer = DMXTimingRestorer()
    
    # 先消耗掉初始的 burst 额度 (发送一帧 I-Frame)
    initial_frame = DMX512Frame(data=bytes([0]*512))
    compressed_init = encoder.encode(initial_frame, force_keyframe=True) # 513 bytes
    limiter.record_send(len(compressed_init))
    
    # 此时 tokens = 1250 - 513 = 737.
    # 模拟全局高频闪烁：每一帧 512 通道在 0 和 255 之间爆闪
    # 验证发送端在 limiter 限速下的丢帧行为：
    total_transmitted_bytes = 0
    tx_frames = []
    
    # 模拟在 0.5 秒钟内以 44.09 Hz 输入 22 帧全爆闪数据
    for frame_idx in range(22):
        val = 255 if frame_idx % 2 == 0 else 0
        frame = DMX512Frame(data=bytes([val]*512))
        
        # 编码
        compressed = encoder.encode(frame, force_keyframe=True)  # 全闪烁被迫退化为 I-Frame (513 Bytes)
        
        # 进行物理限速判定
        if limiter.can_send(len(compressed)):
            limiter.record_send(len(compressed))
            total_transmitted_bytes += len(compressed)
            tx_frames.append(compressed)
            
    # 验证在已消耗 initial burst 后，在 0.5s 的剩余周期内只能再发送 1 帧 513 字节全量帧
    #（即 total_transmitted_bytes <= 513，证明限速器极其严格地执行了 tail-drop 物理截断）
    assert total_transmitted_bytes <= 513
    
    # 验证接收端能否计算精确物理输出时延
    physical_tx_time = restorer.calculate_physical_tx_time_ms(512)
    # 验证标准物理线缆输出一帧 512 通道 DMX 耗时在 22.68 ms 左右
    assert 22.5 < physical_tx_time < 22.8
