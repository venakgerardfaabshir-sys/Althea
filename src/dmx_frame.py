class DMX512Frame:
    """Represents a standard DMX512 frame containing a start code and up to 512 slot values."""
    def __init__(self, start_code: int = 0x00, data: bytes = None):
        self.start_code = start_code
        self.data = data if data is not None else bytes([0]*512)
        if len(self.data) > 512:
            raise ValueError("DMX512 data slot count cannot exceed 512")

    def to_bytes(self) -> bytes:
        """Serializes the DMX512 frame to a bytes object (start code + slot data)."""
        return bytes([self.start_code]) + self.data

    @classmethod
    def from_bytes(cls, raw_data: bytes):
        """Deserializes a raw bytes object into a DMX512Frame."""
        if not raw_data:
            raise ValueError("Empty raw data")
        return cls(start_code=raw_data[0], data=raw_data[1:])
