import time

class BandwidthController:
    """S-FSK link rate limiter: uses token bucket algorithm to guarantee traffic strictly below 10kbps (1250 bytes/s)."""
    def __init__(self, max_bytes_per_sec: int = 1250):
        self.capacity = max_bytes_per_sec
        self.tokens = max_bytes_per_sec
        self.last_update = time.time()
        self.rate = max_bytes_per_sec

    def _refund(self):
        now = time.time()
        elapsed = now - self.last_update
        self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
        self.last_update = now

    def can_send(self, size_bytes: int, is_high_priority: bool = False) -> bool:
        self._refund()
        if is_high_priority and self.tokens >= 0:
            return True
        return self.tokens >= size_bytes

    def record_send(self, size_bytes: int):
        self._refund()
        # Allow tokens to go negative for overdraft to strictly maintain long-term average bandwidth rate
        self.tokens -= size_bytes


class DMXTimingRestorer:
    """DMX512 physical output timing restorer.
    Runs at the receiver side to simulate or control standard physical output timing:
    Baudrate: 250kbps, 8N2 frame format
    - BREAK: Low signal >= 88us (recommended 92us-176us)
    - MAB: High signal >= 8us (recommended 12us)
    - Data: 513 slots (1 start code + 512 channels) at 44us per slot (11 bits * 4us).
    """
    def __init__(self, baudrate: int = 250000):
        self.baudrate = baudrate
        self.break_us = 92
        self.mab_us = 12
        self.slot_bits = 11  # 1 start bit, 8 data bits, 2 stop bits
        self.last_frame_time = time.time()
        self.keepalive_timeout = 2.0  # seconds

    def calculate_physical_tx_time_ms(self, channel_count: int) -> float:
        """Calculates the physical time required to transmit the DMX frame over standard 250kbps line."""
        break_mab_ms = (self.break_us + self.mab_us) / 1000.0
        # channel_count + 1 accounts for the start code byte
        data_ms = (channel_count + 1) * self.slot_bits / self.baudrate * 1000.0
        return break_mab_ms + data_ms
