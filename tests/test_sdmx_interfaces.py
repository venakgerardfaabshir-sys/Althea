import pytest
import time
import sys
import os

# Ensure the src directory is in the path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

from sdmx_interfaces import BandwidthController, DMXTimingRestorer

def test_bandwidth_limiting():
    # Test that the token bucket rate limiter strictly bounds traffic
    limiter = BandwidthController(max_bytes_per_sec=1250)
    
    start_time = time.time()
    total_sent = 0
    payload = b"X" * 100
    
    # Send as much as possible for 0.3 seconds
    while time.time() - start_time < 0.3:
        if limiter.can_send(len(payload)):
            limiter.record_send(len(payload))
            total_sent += len(payload)
        else:
            time.sleep(0.01)
            
    elapsed = time.time() - start_time
    
    # The mathematical bound of token bucket is: Total Sent <= Initial Tokens + Rate * Elapsed
    max_allowed = limiter.capacity + limiter.rate * elapsed
    assert total_sent <= max_allowed + 100  # allow 1 packet rounding error

def test_dmx_timing_calculation():
    restorer = DMXTimingRestorer()
    # 验证标准物理线缆输出一帧 512 通道 DMX 耗时在 22.68 ms 左右
    physical_tx_time = restorer.calculate_physical_tx_time_ms(512)
    assert 22.5 < physical_tx_time < 22.8
