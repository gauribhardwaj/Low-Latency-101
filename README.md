# Low-Latency-101
The Universal Low Latency Runbook: Resilient Performance Across Languages

This repository provides practical examples and best practices for writing low-latency code in multiple programming languages.
It includes performance profiling guides, before/after examples, and a universal latency optimization checklist.
"""

# Python Examples
python_naive = '''
# naive.py
def process_data(data):
    results = []
    for item in data:
        results.append(compute(item))
    return results
'''

python_optimized = '''
# optimized.py
def process_data(data):
    compute_fn = compute_fast if len(data) > 1000 else compute_safe
    results = [None] * len(data)
    for i in range(len(data)):
        results[i] = compute_fn(data[i])
    return results
'''

# Java placeholder
java_naive = '// naive.java\npublic class Naive { public void process() { /* slow code */ } }'
java_optimized = '// optimized.java\npublic class Optimized { public void process() { /* optimized code */ } }'

# Checklist Content
latency_checklist = """
# Latency Survival Checklist

## 🔥 Hot Path
- [ ] No allocations inside loops
- [ ] Use arrays over maps for predictable access
- [ ] Avoid locks or use lock-free data structures

## 🧠 Memory
- [ ] Object pooling
- [ ] Minimize GC pressure

## ⚡ CPU
- [ ] Loop unrolling
- [ ] Minimize branching

## 🌐 I/O
- [ ] Batch requests
- [ ] Use non-blocking calls

## 🧰 Tools
- [ ] perf
- [ ] async-profiler
- [ ] flamegraph
"""

# The actual implementation can now fill in each file/language
# and commit this to a public GitHub repo
