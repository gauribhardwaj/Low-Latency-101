# Java Packet Engine (Single-Core, Netty + Agrona + JMH)

Drop-in module for **Low-Latency-101** showcasing a **single-core, run-to-completion** packet pipeline:
- **Netty** server with Linux epoll and manual backpressure (no parallelism)
- **Agrona** SPSC ring buffer demo (lock-free handoff pattern)
- **JMH** microbench for a byte-wise transform (baseline perf)

> Folder: `engines/java-packet-engine/`

---

## Quick Start

### 0) Requirements
- JDK **21+**
- Linux recommended for epoll and tuning
- Gradle (or run `gradle wrapper` once to generate `./gradlew`)

### 1) Run the server (single thread)
```bash
cd engines/java-packet-engine

# Optional: generate wrapper if you have Gradle installed
gradle wrapper

# Pin to core 3 and use ZGC (example). Adjust core/heap as needed.
taskset -c 3 ./gradlew run   -Dorg.gradle.jvmargs="-XX:+UseZGC -Xms512m -Xmx512m -XX:+AlwaysPreTouch"
```

Env / flags:
- `PORT` (default `9000`)
- `BUSY_POLL` (`true|false`, default `false`) — set `true` to busy-read the channel for demo

### 2) Talk to the server
Send a line, it returns the **XOR-transformed** bytes (0x5A) to show in-place transforms.

```bash
# simple test
printf "hello\n" | nc localhost 9000 -N | hexdump -C
```

### 3) Run the ring buffer demo
```bash
# (in another terminal)
taskset -c 3 ./gradlew -q run --args="--spsc-demo 1e6"
```

### 4) Run microbenchmarks
```bash
./gradlew jmh
# Look for results under build/reports/jmh/ and build/results/jmh/
```

---

## Linux knobs (optional, use on dedicated host)

```bash
# Reduce scheduling jitter on the app core:
#  - Isolate a CPU via grub cmdline (needs reboot):
#    isolcpus=3 nohz_full=3 rcu_nocbs=3
#  - Move IRQs off core 3 (ethtool + /proc/irq/*/smp_affinity)
#  - Force performance governor:
sudo cpupower frequency-set -g performance

# Busy poll (trades CPU for latency). Values are in microseconds:
sudo sysctl -w net.core.busy_read=50
sudo sysctl -w net.core.busy_poll=50
```

---

## Project Layout

```
java-packet-engine/
  build.gradle
  settings.gradle
  README.md
  src/
    main/java/com/lowlatency/packet/
      OneCorePacketServer.java        # Netty single-threaded server
      ProcessingPipeline.java         # decode -> transform -> encode
      client/Client.java              # tiny client to blast packets
      ring/SpscDemo.java              # Agrona OneToOneRingBuffer example
    jmh/java/com/lowlatency/packet/bench/
      TransformBench.java             # JMH microbench (byte[] xor)
```

---

## Notes

- The server disables auto-read and **pulls** only when the socket is writable (manual backpressure).
- No GC pressure in the hot path: pooled buffers, in-place ops, and zero unnecessary allocations.
- For extreme setups, graduate to AF_XDP or DPDK (requires JNI) after you prove kernel path is the bottleneck.
- Use **JFR** for perf profiling in long runs (not included here to keep the module lean).

---

## License
MIT (template code). Replace/modify freely.
