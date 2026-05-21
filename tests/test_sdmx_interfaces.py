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

def test_bandwidth_priority_overdraft():
    # Test that high priority sends can bypass rate limit if tokens >= 0,
    # and drive the tokens negative, while subsequent sends are blocked.
    limiter = BandwidthController(max_bytes_per_sec=1000)
    
    # DMX initial token is 1000.
    # 1. Send normal packet of 900 bytes.
    assert limiter.can_send(900, is_high_priority=False)
    limiter.record_send(900)
    assert limiter.tokens == pytest.approx(100.0, abs=5.0)
    
    # 2. Try to send another 500 bytes packet normally (should fail because 100 < 500)
    assert not limiter.can_send(500, is_high_priority=False)
    
    # 3. Send 500 bytes packet with high priority (should succeed because tokens 100 >= 0)
    assert limiter.can_send(500, is_high_priority=True)
    limiter.record_send(500)
    
    # 4. Check that token goes negative (-400)
    assert limiter.tokens == pytest.approx(-400.0, abs=5.0)
    
    # 5. While tokens is negative, both normal and high priority sends are blocked
    assert not limiter.can_send(10, is_high_priority=False)
    assert not limiter.can_send(10, is_high_priority=True)
