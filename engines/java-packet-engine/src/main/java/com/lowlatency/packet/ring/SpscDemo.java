package com.lowlatency.packet.ring;

import org.agrona.MutableDirectBuffer;
import org.agrona.concurrent.MessageHandler;
import org.agrona.concurrent.UnsafeBuffer;
import org.agrona.concurrent.ringbuffer.OneToOneRingBuffer;
import org.agrona.concurrent.ringbuffer.RingBufferDescriptor;

import java.nio.ByteBuffer;
import java.util.concurrent.TimeUnit;

/**
 * Minimal SPSC ring buffer demo using Agrona.
 * Writer publishes longs, reader consumes and sums them.
 *
 * Usage (from Gradle run):
 *   ./gradlew -q run --args="--spsc-demo 1e6"
 */
public final class SpscDemo {

    public static void main(String[] args) {
        long n = 1_000_000L;
        if (args.length >= 2 && args[0].equals("--spsc-demo")) {
            String count = args[1];
            if (count.endsWith("e6")) n = 1_000_000L;
            else n = (long) Double.parseDouble(count);
            run(n);
        } else {
            System.out.println("Run with: --spsc-demo <count>   (e.g., 1e6)");
        }
    }

    private static void run(long n) {
        final int capacity = 1024 * 1024; // power of two recommended
        final int trailer = RingBufferDescriptor.TRAILER_LENGTH;
        final ByteBuffer buffer = ByteBuffer.allocateDirect(capacity + trailer);
        final UnsafeBuffer ub = new UnsafeBuffer(buffer);
        final OneToOneRingBuffer ring = new OneToOneRingBuffer(ub);

        final int msgType = 1;
        final int msgLen = Long.BYTES;
        final ByteBuffer srcDirect = ByteBuffer.allocateDirect(msgLen);
        final UnsafeBuffer src = new UnsafeBuffer(srcDirect);

        final long start = System.nanoTime();

        // Reader
        final Thread reader = new Thread(() -> {
            final long[] sum = {0L};
            final MessageHandler handler = (typeId, buf, index, length) -> {
                sum[0] += buf.getLong(index);
            };
            long consumed = 0;
            while (consumed < n) {
                int read = ring.read(handler);
                if (read == 0) {
                    Thread.onSpinWait();
                } else {
                    consumed += read;
                }
            }
            long tookNs = System.nanoTime() - start;
            double rate = (double) n / (tookNs / 1_000_000_000.0);
            System.out.printf("SPSC consumed %,d msgs, sum=%d, rate=%.0f msg/s%n", n, sum[0], rate);
        }, "spsc-reader");

        reader.start();

        // Writer
        for (long i = 0; i < n; i++) {
            src.putLong(0, i);
            while (!ring.write(msgType, src, 0, msgLen)) {
                Thread.onSpinWait();
            }
        }

        try { reader.join(); } catch (InterruptedException ignored) {}
    }
}
