package com.lowlatency.packet.client;

import java.io.BufferedOutputStream;
import java.io.IOException;
import java.net.Socket;
import java.util.concurrent.ThreadLocalRandom;

/** Tiny client to blast lines to the server. */
public final class Client {
    public static void main(String[] args) throws Exception {
        String host = args.length > 0 ? args[0] : "127.0.0.1";
        int port = args.length > 1 ? Integer.parseInt(args[1]) : 9000;
        long messages = args.length > 2 ? Long.parseLong(args[2]) : 1_000;

        try (Socket s = new Socket(host, port);
             BufferedOutputStream out = new BufferedOutputStream(s.getOutputStream())) {
            byte[] payload = new byte[128];
            for (long i = 0; i < messages; i++) {
                // Fill with pseudo-random bytes and a newline terminator
                ThreadLocalRandom.current().nextBytes(payload);
                out.write(payload);
                out.write('\n');
            }
            out.flush();
        } catch (IOException e) {
            e.printStackTrace();
        }
    }
}
