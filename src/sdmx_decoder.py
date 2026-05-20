from dmx_frame import DMX512Frame

class SDMXDecoder:
    """Decompressor that reconstructs DMX512 frames from compressed S-DMX packets."""
    def __init__(self):
        self.state = bytearray([0]*512)
        self.last_seq = -1
        self.sync_lost = True

    def decode(self, packet: bytes) -> DMX512Frame:
        if not packet:
            raise ValueError("Empty packet")
            
        header = packet[0]
        seq = (header >> 4) & 0x0F
        frame_type = header & 0x0F
        
        # 1. Packet Loss / Out-of-Sync Detection
        if self.last_seq != -1:
            expected_seq = (self.last_seq + 1) % 16
            # If sequence gap detected and it is not an I-Frame (0x01), mark sync lost
            if seq != expected_seq and frame_type != 0x01:
                self.sync_lost = True
                
        self.last_seq = seq

        # 2. Frame Decoding
        if frame_type == 0x01:  # I-Frame (Full frame)
            if len(packet) < 513:
                raise ValueError("Corrupt I-Frame packet size")
            self.state = bytearray(packet[1:513])
            self.sync_lost = False
        elif self.sync_lost:
            # If sync is lost, incremental updates are ignored to prevent corrupted states
            return DMX512Frame(data=bytes(self.state))
        elif frame_type == 0x02:  # P-Frame Sparse
            count = packet[1]
            offset = 2
            for _ in range(count):
                idx = (packet[offset] << 8) | packet[offset+1]
                val = packet[offset+2]
                self.state[idx] = val
                offset += 3
        elif frame_type == 0x03:  # P-Frame Bitmap
            bitmap = packet[1:65]
            offset = 65
            for idx in range(512):
                byte_idx = idx // 8
                bit_idx = idx % 8
                if bitmap[byte_idx] & (1 << bit_idx):
                    self.state[idx] = packet[offset]
                    offset += 1
        elif frame_type == 0x04:  # P-Frame Range
            start = (packet[1] << 8) | packet[2]
            span = (packet[3] << 8) | packet[4]
            data = packet[5:5+span]
            self.state[start:start+span] = data
        elif frame_type == 0x05:  # Keepalive
            pass  # State remains unchanged
        else:
            raise ValueError(f"Unknown S-DMX frame type: {frame_type}")

        return DMX512Frame(data=bytes(self.state))
