#!/usr/bin/env python3
"""
Binary reading utilities for XBG files
"""

import struct
from typing import Tuple, List


def half_to_float(h: int) -> int:
    """Convert 16-bit half precision float to 32-bit float"""
    s = int((h >> 15) & 0x00000001)  # sign
    e = int((h >> 10) & 0x0000001f)  # exponent
    f = int(h & 0x000003ff)          # fraction

    if e == 0:
        if f == 0:
            return int(s << 31)
        else:
            while not (f & 0x00000400):
                f <<= 1
                e -= 1
            e += 1
            f &= ~0x00000400
    elif e == 31:
        if f == 0:
            return int((s << 31) | 0x7f800000)
        else:
            return int((s << 31) | 0x7f800000 | (f << 13))

    e = e + (127 - 15)
    f = f << 13
    return int((s << 31) | (e << 23) | f)


def convert_half_to_float(h: int) -> float:
    """Convert half precision to float"""
    id = half_to_float(h)
    return struct.unpack('f', struct.pack('I', id))[0]


class BinaryReader:
    """Binary reader for game files"""
    
    def __init__(self, file_path: str):
        self.file = open(file_path, 'rb')
        self.endian = '<'
        self.debug = False
        
    def __enter__(self):
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.file.close()
    
    def tell(self) -> int:
        return self.file.tell()
    
    def seek(self, offset: int, whence: int = 0):
        self.file.seek(offset, whence)
    
    def seekpad(self, pad: int, type: int = 0):
        """16-byte chunk alignment"""
        size = self.file.tell()
        seek = (pad - (size % pad)) % pad
        if type == 1:
            if seek == 0:
                seek += pad
        self.file.seek(seek, 1)
    
    def file_size(self) -> int:
        back = self.file.tell()
        self.file.seek(0, 2)
        size = self.file.tell()
        self.file.seek(back)
        return size
    
    def read(self, count: int) -> bytes:
        return self.file.read(count)
    
    def i(self, n: int) -> Tuple:
        """Read n integers"""
        return struct.unpack(self.endian + n * 'i', self.file.read(n * 4))
    
    def I(self, n: int) -> Tuple:
        """Read n unsigned integers"""
        return struct.unpack(self.endian + n * 'I', self.file.read(n * 4))
    
    def h(self, n: int) -> Tuple:
        """Read n shorts"""
        return struct.unpack(self.endian + n * 'h', self.file.read(n * 2))
    
    def H(self, n: int) -> Tuple:
        """Read n unsigned shorts"""
        return struct.unpack(self.endian + n * 'H', self.file.read(n * 2))
    
    def f(self, n: int) -> Tuple:
        """Read n floats"""
        return struct.unpack(self.endian + n * 'f', self.file.read(n * 4))
    
    def B(self, n: int) -> Tuple:
        """Read n unsigned bytes"""
        return struct.unpack(self.endian + n * 'B', self.file.read(n))
    
    def b(self, n: int) -> Tuple:
        """Read n signed bytes"""
        return struct.unpack(self.endian + n * 'b', self.file.read(n))
    
    def word(self, length: int) -> str:
        """Read a string of given length"""
        s = ''
        for j in range(length):
            lit = struct.unpack('c', self.file.read(1))[0]
            if ord(lit) != 0:
                s += lit.decode('utf-8', errors='ignore')
        return s