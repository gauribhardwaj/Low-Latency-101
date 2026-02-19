import uvloop
import asyncio
import numpy as np
from numba import jit
import selectors


@jit(nopython=True)
def fast(n):
    total = 0
    for i in range(n):
        total += i
    return total


def io_multiplex():
    sel = selectors.DefaultSelector()
    return sel


async def main():
    loop = asyncio.get_running_loop()
    arr = np.frombuffer(bytearray(b"123456"), dtype=np.uint8)
    return loop, arr

