package com.lowlatency.packet.bench;

import org.openjdk.jmh.annotations.*;
import org.openjdk.jmh.infra.Blackhole;

import java.nio.ByteBuffer;
import java.util.concurrent.TimeUnit;

/**
 * Microbench: XOR in-place on a direct ByteBuffer.
 */
@BenchmarkMode(Mode.AverageTime)
@OutputTimeUnit(TimeUnit.NANOSECONDS)
@State(Scope.Thread)
public class TransformBench {

    @Param({"64", "256", "1024"})
    public int size;

    private ByteBuffer buf;

    @Setup(Level.Iteration)
    public void setup() {
        buf = ByteBuffer.allocateDirect(size);
        for (int i = 0; i < size; i++) buf.put((byte)(i & 0xFF));
        buf.flip();
    }

    @Benchmark
    public void xor_direct(Blackhole bh) {
        final byte key = 0x5A;
        int pos = buf.position();
        int limit = buf.limit();
        for (int i = pos; i < limit; i++) {
            byte b = buf.get(i);
            buf.put(i, (byte)(b ^ key));
        }
        // keep the buffer "live"
        bh.consume(buf.get(0));
    }
}
