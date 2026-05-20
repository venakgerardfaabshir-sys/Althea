from dmx_frame import DMX512Frame

class SDMXEncoder:
    """Adaptive multi-mode S-DMX compressor with flicker filtering and bandwidth awareness."""
    def __init__(self, flicker_threshold: int = 1):
        self.last_state = bytes([0]*512)
        self.seq = 0
        self.flicker_threshold = flicker_threshold

    def get_next_seq(self) -> int:
        current_seq = self.seq
        self.seq = (self.seq + 1) % 16
        return current_seq

    def encode(self, frame: DMX512Frame, force_keyframe: bool = False) -> bytes:
        seq = self.get_next_seq()
        current_data = frame.data
        
        # 1. Flicker Filtering: mute tiny, meaningless jitters
        filtered_data = bytearray(current_data)
        for i in range(512):
            diff = abs(current_data[i] - self.last_state[i])
            if diff <= self.flicker_threshold:
                filtered_data[i] = self.last_state[i]
        filtered_data = bytes(filtered_data)

        # 2. Check if anything changed
        if filtered_data == self.last_state and not force_keyframe:
            # Keepalive Frame: 1 byte
            header = (seq << 4) | 0x05
            return bytes([header])

        # 3. Collect changed indices
        changed_indices = [i for i in range(512) if filtered_data[i] != self.last_state[i]]
        
        # If force_keyframe or too many channels changed, fallback to I-Frame
        if force_keyframe or len(changed_indices) > 400:
            header = (seq << 4) | 0x01
            self.last_state = filtered_data
            return bytes([header]) + filtered_data

        # Determine best compression mode
        # Mode A: P-Frame Sparse (Header + Count + N * [Idx(2) + Val(1)])
        sparse_size = 2 + len(changed_indices) * 3
        
        # Mode B: P-Frame Bitmap (Header + Bitmap(64) + N * Val(1))
        bitmap_size = 1 + 64 + len(changed_indices)

        # Mode C: P-Frame Range (Header + Start(2) + Span(2) + Span * Val(1))
        range_size = float('inf')
        if changed_indices:
            start, end = changed_indices[0], changed_indices[-1]
            span = end - start + 1
            range_size = 5 + span

        best_mode = 'sparse'
        min_size = sparse_size
        
        if bitmap_size < min_size:
            best_mode = 'bitmap'
            min_size = bitmap_size
        if range_size < min_size:
            best_mode = 'range'
            min_size = range_size

        # 4. Perform optimal encoding
        header = (seq << 4)
        if best_mode == 'sparse':
            header |= 0x02
            payload = bytearray([header, len(changed_indices)])
            for idx in changed_indices:
                payload.append((idx >> 8) & 0xFF)
                payload.append(idx & 0xFF)
                payload.append(filtered_data[idx])
        elif best_mode == 'bitmap':
            header |= 0x03
            bitmap = bytearray(64)
            data_part = bytearray()
            for idx in changed_indices:
                bitmap[idx // 8] |= (1 << (idx % 8))
                data_part.append(filtered_data[idx])
            payload = bytearray([header]) + bitmap + data_part
        else:  # range
            header |= 0x04
            start = changed_indices[0]
            span = changed_indices[-1] - start + 1
            payload = bytearray([header])
            payload.append((start >> 8) & 0xFF)
            payload.append(start & 0xFF)
            payload.append((span >> 8) & 0xFF)
            payload.append(span & 0xFF)
            payload.extend(filtered_data[start:start+span])

        self.last_state = filtered_data
        return bytes(payload)
