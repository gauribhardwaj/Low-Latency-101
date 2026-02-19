buf = bytearray(b"\x00" * 1024)
mv = memoryview(buf)
for i in range(0, len(mv), 8):
    chunk = mv[i : i + 8]

