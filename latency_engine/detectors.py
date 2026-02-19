import ast
import re
import logging
from typing import Dict, List

logger = logging.getLogger(__name__)


class DetectorResult:
    def __init__(self) -> None:
        self.issues: List[Dict] = []
        self.positive_signals: List[str] = []

    def to_dict(self) -> Dict:
        return {
            "issues": self.issues,
            "positive_signals": self.positive_signals,
        }


class PythonDetector(ast.NodeVisitor):
    """AST-based heuristics for Python latency issues and positive signals.

    This detector focuses on loop hot-paths and common latency pitfalls,
    plus surfaces language-specific "secret sauce" APIs when present.
    """

    def __init__(self, code: str) -> None:
        self.code = code
        self.tree = None
        try:
            self.tree = ast.parse(code)
        except Exception:
            # If parsing fails, we won't provide AST-based findings
            self.tree = None
        self.res = DetectorResult()

    def analyze(self) -> DetectorResult:
        logger.info("PythonDetector: analyze start")
        self._scan_imports_for_positive_signals()
        if self.tree is not None:
            self.visit(self.tree)
        else:
            logger.warning("PythonDetector: AST parse failed; using regex fallback")
            # Fallback: simple regex hints when AST parsing fails
            self._regex_fallback()
        logger.info(
            "PythonDetector: analyze end (issues=%d, positives=%d)",
            len(self.res.issues),
            len(self.res.positive_signals),
        )
        return self.res

    # ---------- Positive signals ----------
    def _scan_imports_for_positive_signals(self) -> None:
        text = self.code
        positive_patterns = [
            (r"\bimport\s+uvloop\b|\bfrom\s+uvloop\s+import\b", "uvloop event loop (fast asyncio)"),
            (r"\bimport\s+numpy\b|\bfrom\s+numpy\s+import\b", "NumPy (vectorized ops)"),
            (r"\bfrom\s+numba\s+import\s+jit\b|@jit\b", "Numba JIT accelerators"),
            (r"\bfrom\s+multiprocessing\s+import\s+shared_memory\b", "Shared memory (zero-copy IPC)"),
            (r"\bimport\s+mmap\b", "mmap (file-backed memory)"),
            (r"\bfrom\s+collections\s+import\s+deque\b", "collections.deque (amortized O(1))"),
            (r"\bimport\s+selectors\b", "selectors (efficient I/O multiplexing)"),
        ]
        for pat, label in positive_patterns:
            if re.search(pat, text):
                self.res.positive_signals.append(label)

    # ---------- AST Helpers ----------
    def _in_loop(self, node: ast.AST) -> bool:
        parent = getattr(node, "parent", None)
        while parent is not None:
            if isinstance(parent, (ast.For, ast.While, ast.AsyncFor)):
                return True
            parent = getattr(parent, "parent", None)
        return False

    def generic_visit(self, node: ast.AST) -> None:
        for child in ast.iter_child_nodes(node):
            setattr(child, "parent", node)
        super().generic_visit(node)

    # ---------- Visitors ----------
    def visit_Call(self, node: ast.Call) -> None:
        func_name = self._qualname(node.func)
        in_loop = self._in_loop(node)

        # Anti-patterns in hot loops
        if in_loop and func_name in {
            "print",
            "logging.debug",
            "logging.info",
            "logging.warning",
            "logging.error",
            "logging.critical",
            "time.sleep",
            "subprocess.run",
            "subprocess.Popen",
            "os.system",
            "json.dumps",
            "json.loads",
            "re.compile",
            "open",
            "requests.get",
            "requests.post",
        }:
            self._issue(
                rule=f"Call to {func_name} in hot loop",
                message=(
                    f"Avoid calling `{func_name}` inside loops. Batch or hoist outside."
                ),
                penalty=8,
            )

        # Regex compilation inside loop is particularly bad
        if in_loop and func_name == "re.compile":
            self._issue(
                rule="Regex compile in loop",
                message="Move re.compile outside the loop and reuse the pattern.",
                penalty=10,
            )

        # Positive signals by API usage
        positive_by_call = {
            "numpy.array": "NumPy arrays used",
            "numpy.frombuffer": "Zero-copy NumPy frombuffer",
            "memoryview": "memoryview for zero-copy slicing",
            "bytearray": "bytearray for mutable bytes",
            "selectors.DefaultSelector": "Using selectors for I/O multiplexing",
            "asyncio.get_running_loop": "AsyncIO event loop in use",
        }
        if func_name in positive_by_call:
            self.res.positive_signals.append(positive_by_call[func_name])

        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        if self._in_loop(node):
            # Literal containers allocated inside loop
            if isinstance(node.value, (ast.List, ast.Set, ast.Dict)):
                self._issue(
                    rule="Container allocation inside loop",
                    message="Avoid allocating lists/sets/dicts in loops; reuse or preallocate.",
                    penalty=7,
                )
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        if self._in_loop(node) and isinstance(node.op, ast.Add):
            # Heuristic: string concat in loop (s += t)
            if isinstance(node.target, ast.Name) and isinstance(node.value, (ast.Str, ast.JoinedStr)):
                self._issue(
                    rule="String concatenation in loop",
                    message="Use list-join or io.StringIO for building strings in loops.",
                    penalty=6,
                )
        self.generic_visit(node)

    # ---------- Utils ----------
    def _qualname(self, node: ast.AST) -> str:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            parts: List[str] = []
            cur: ast.AST = node
            while isinstance(cur, ast.Attribute):
                parts.append(cur.attr)
                cur = cur.value
            if isinstance(cur, ast.Name):
                parts.append(cur.id)
            return ".".join(reversed(parts))
        return ""

    def _issue(self, rule: str, message: str, penalty: int) -> None:
        self.res.issues.append({
            "rule": rule,
            "message": message,
            "penalty": penalty,
        })

    def _regex_fallback(self) -> None:
        # Minimal fallbacks if AST parse fails
        text = self.code
        if re.search(r"\bprint\s*\(", text):
            self._issue("print usage", "Printing can be slow in hot paths.", 4)


class JavaDetector:
    """Token/regex-based heuristics for Java latency issues and positive signals."""

    POSITIVE_IMPORTS = [
        (r"\bimport\s+com\.lmax\.disruptor\b", "LMAX Disruptor (ring buffer)"),
        (r"\bimport\s+org\.agrona\b", "Agrona (low-latency primitives)"),
        (r"\bimport\s+io\.aeron\b", "Aeron (media driver / IPC)"),
        (r"\bimport\s+net\.openhft\.chronicle\b", "Chronicle (zero-GC queues/map)"),
        (r"\bimport\s+io\.netty\b", "Netty (event-driven NIO)"),
        (r"\bimport\s+org\.openjdk\.jmh\b", "JMH (microbenchmarking)"),
    ]

    NEGATIVE_PATTERNS = [
        (r"System\.out\.println\s*\(", 12, "Avoid System.out in hot paths; buffer or disable."),
        (r"new\s+\w+\s*\(.*\)\s*;", 8, "Object allocation may pressure GC; consider reuse/pooling."),
        (r"synchronized\s*\(", 10, "Synchronization in hot paths can throttle throughput."),
        (r"String\s*\+\s*\w|\w\s*\+\s*String", 6, "String concatenation; prefer StringBuilder."),
        (r"Thread\.sleep\s*\(", 8, "Sleeping in critical paths adds latency."),
    ]

    POSITIVE_CALLS = [
        (r"LongAdder", "LongAdder (reduced contention counter)"),
        (r"VarHandle", "VarHandle (low-level memory ops)"),
        (r"ByteBuffer\.allocateDirect", "Direct ByteBuffer (off-heap)"),
        (r"Epoll|KQueue", "Native transport (epoll/kqueue)"),
    ]

    def __init__(self, code: str) -> None:
        self.code = code

    def analyze(self) -> DetectorResult:
        logger.info("JavaDetector: analyze start")
        res = DetectorResult()
        text = self.code
        for pat, label in self.POSITIVE_IMPORTS:
            if re.search(pat, text):
                res.positive_signals.append(label)
        for pat, label in self.POSITIVE_CALLS:
            if re.search(pat, text):
                res.positive_signals.append(label)
        for pat, penalty, msg in self.NEGATIVE_PATTERNS:
            if re.search(pat, text):
                res.issues.append({"rule": "Java pattern", "message": msg, "penalty": penalty})
        logger.info(
            "JavaDetector: analyze end (issues=%d, positives=%d)",
            len(res.issues),
            len(res.positive_signals),
        )
        return res


class CppDetector:
    """Regex heuristics for C++ latency issues and positive signals."""

    POSITIVE_INCLUDES = [
        (r"#include\s*<boost/lockfree/", "Boost lockfree structures"),
        (r"#include\s*<folly/", "Facebook Folly performance primitives"),
        (r"#include\s*<absl/", "Abseil containers/arenas"),
        (r"#include\s*<memory_resource>", "std::pmr polymorphic allocators"),
    ]

    NEGATIVE_PATTERNS = [
        (r"std::cout\s*<<", 12, "std::cout in hot paths causes I/O stalls."),
        (r"new\s+\w+\s*\(|malloc\s*\(", 10, "Dynamic allocation in loops increases latency/fragmentation."),
        (r"std::shared_ptr\s*<", 6, "shared_ptr has atomic refcount; avoid in hot loops."),
        (r"std::function\s*<", 6, "std::function type erasure incurs overhead; avoid in loops."),
        (r"virtual\s+\w+\s*\(", 4, "Virtual dispatch in hot loops can hurt branch prediction."),
    ]

    def __init__(self, code: str) -> None:
        self.code = code

    def analyze(self) -> DetectorResult:
        logger.info("CppDetector: analyze start")
        res = DetectorResult()
        text = self.code
        for pat, label in self.POSITIVE_INCLUDES:
            if re.search(pat, text):
                res.positive_signals.append(label)
        for pat, penalty, msg in self.NEGATIVE_PATTERNS:
            if re.search(pat, text):
                res.issues.append({"rule": "C++ pattern", "message": msg, "penalty": penalty})
        logger.info(
            "CppDetector: analyze end (issues=%d, positives=%d)",
            len(res.issues),
            len(res.positive_signals),
        )
        return res
