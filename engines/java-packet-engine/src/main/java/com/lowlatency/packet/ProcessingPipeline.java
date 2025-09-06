package com.lowlatency.packet;

import io.netty.buffer.ByteBuf;

/** Tiny, allocation-free transforms for demo purposes. */
public final class ProcessingPipeline {
    private ProcessingPipeline() {}

    /** In-place XOR transform over the readable bytes. */
    public static void xorInPlace(ByteBuf buf, byte key) {
        int idx = buf.readerIndex();
        int end = buf.writerIndex();
        for (int i = idx; i < end; i++) {
            byte b = buf.getByte(i);
            buf.setByte(i, b ^ key);
        }
    }
}
