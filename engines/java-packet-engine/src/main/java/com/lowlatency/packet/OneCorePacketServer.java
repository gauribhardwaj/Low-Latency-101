package com.lowlatency.packet;

import io.netty.bootstrap.ServerBootstrap;
import io.netty.buffer.ByteBuf;
import io.netty.channel.*;
import io.netty.channel.epoll.Epoll;
import io.netty.channel.epoll.EpollEventLoopGroup;
import io.netty.channel.epoll.EpollServerSocketChannel;
import io.netty.channel.nio.NioEventLoopGroup;
import io.netty.channel.socket.SocketChannel;
import io.netty.channel.socket.nio.NioServerSocketChannel;

import java.nio.charset.StandardCharsets;
import java.util.concurrent.TimeUnit;

/**
 * Single-core, single-event-loop Netty server.
 * - AUTO_READ=false for manual backpressure
 * - Epoll if available, otherwise NIO
 * - In-place XOR transform (0x5A) to show low-allocation processing
 */
public final class OneCorePacketServer {

    public static void main(String[] args) throws Exception {
        final int port = Integer.parseInt(System.getenv().getOrDefault("PORT", "9000"));
        final boolean epoll = Epoll.isAvailable();
        final boolean busyPollDemo = Boolean.parseBoolean(System.getenv().getOrDefault("BUSY_POLL", "false"));

        final EventLoopGroup group = epoll ? new EpollEventLoopGroup(1) : new NioEventLoopGroup(1);

        try {
            ServerBootstrap b = new ServerBootstrap()
                    .group(group)
                    .channel(epoll ? EpollServerSocketChannel.class : NioServerSocketChannel.class)
                    .option(ChannelOption.SO_REUSEADDR, true)
                    .childOption(ChannelOption.TCP_NODELAY, true)
                    .childOption(ChannelOption.SO_RCVBUF, 1 << 20)
                    .childOption(ChannelOption.SO_SNDBUF, 1 << 20)
                    .childOption(ChannelOption.AUTO_READ, false) // manual backpressure
                    .childHandler(new ChannelInitializer<SocketChannel>() {
                        @Override protected void initChannel(SocketChannel ch) {
                            ChannelPipeline p = ch.pipeline();
                            p.addLast(new InboundHandler(busyPollDemo));
                        }
                    });

            Channel ch = b.bind(port).sync().channel();
            System.out.printf("OneCorePacketServer listening on %d (epoll=%s, busyPollDemo=%s)%n",
                    port, epoll, busyPollDemo);
            ch.closeFuture().sync();
        } finally {
            group.shutdownGracefully();
        }
    }

    static final class InboundHandler extends ChannelInboundHandlerAdapter {
        private final boolean busyPollDemo;

        InboundHandler(boolean busyPollDemo) { this.busyPollDemo = busyPollDemo; }

        @Override public void channelActive(ChannelHandlerContext ctx) {
            if (busyPollDemo) {
                // Busy-poll style: schedule immediate reads; avoid AUTO_READ to control backpressure.
                ctx.executor().scheduleAtFixedRate(() -> safeRead(ctx), 0, 50, TimeUnit.MICROSECONDS);
            } else {
                ctx.read(); // pull first batch
            }
        }

        private void safeRead(ChannelHandlerContext ctx) {
            if (ctx.channel().isActive() && ctx.channel().isReadable() && ctx.channel().isWritable()) {
                ctx.read();
            }
        }

        @Override public void channelRead(ChannelHandlerContext ctx, Object msg) {
            ByteBuf in = (ByteBuf) msg;
            try {
                // Process in-place: decode -> transform -> encode.
                // For demo, XOR each readable byte by 0x5A and echo.
                ProcessingPipeline.xorInPlace(in, (byte) 0x5A);
                ctx.write(in.retain());
            } finally {
                in.release();
            }
        }

        @Override public void channelReadComplete(ChannelHandlerContext ctx) {
            ctx.flush();
            if (!busyPollDemo && ctx.channel().isWritable()) {
                ctx.read(); // pull next batch only when writable (manual backpressure)
            }
        }

        @Override public void channelWritabilityChanged(ChannelHandlerContext ctx) {
            if (!busyPollDemo && ctx.channel().isWritable()) {
                ctx.read();
            }
        }

        @Override public void exceptionCaught(ChannelHandlerContext ctx, Throwable cause) {
            // Avoid noisy stacktraces on client disconnects
            String m = cause.getMessage();
            if (m == null || (!m.contains("Connection reset") && !m.contains("Broken pipe"))) {
                cause.printStackTrace();
            }
            ctx.close();
        }
    }
}
