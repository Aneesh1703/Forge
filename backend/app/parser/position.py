import bisect


class BytePositionMapper:
    """
    Translates byte offsets into 0-indexed (line, column) positions
    in O(log L) time using precomputed newline byte indices.
    """

    def __init__(self, source: bytes) -> None:
        self._line_starts = [0]
        for idx, byte in enumerate(source):
            if byte == 10:
                self._line_starts.append(idx + 1)

    def position(self, byte_offset: int) -> tuple[int, int]:
        """
        Returns (line, column) for a given byte offset (0-indexed).
        """
        if byte_offset <= 0:
            return (0, 0)
        line = bisect.bisect_right(self._line_starts, byte_offset) - 1
        col = byte_offset - self._line_starts[line]
        return (line, col)
