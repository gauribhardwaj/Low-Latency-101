import ast
import re
import logging
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional library imports — graceful fallback to regex when not installed
# ---------------------------------------------------------------------------
try:
    import javalang
    _JAVALANG = True
except ImportError:
    _JAVALANG = False
    logger.debug("javalang not available; Java detector falls back to regex")

try:
    from tree_sitter import Language, Parser as _TSParser
    import tree_sitter_cpp as _tscpp
    _CPP_LANGUAGE = Language(_tscpp.language())
    _TREE_SITTER_CPP = True
except Exception:
    _TREE_SITTER_CPP = False
    logger.debug("tree-sitter-cpp not available; C++ detector falls back to regex")


class DetectorResult:
    def __init__(self) -> None:
        self.issues: List[Dict] = []
        self.positive_signals: List[str] = []

    def to_dict(self) -> Dict:
        return {
            "issues": self.issues,
            "positive_signals": self.positive_signals,
        }


# ---------------------------------------------------------------------------
# Python detector — uses stdlib ast (already proper AST, no new dep needed)
# ---------------------------------------------------------------------------

class PythonDetector(ast.NodeVisitor):
    """AST-based heuristics for Python latency issues and positive signals."""

    def __init__(self, code: str) -> None:
        self.code = code
        self.tree = None
        try:
            self.tree = ast.parse(code)
        except Exception:
            self.tree = None
        self.res = DetectorResult()
        self._nested_loop_reported = False

    def analyze(self) -> DetectorResult:
        logger.info("PythonDetector: analyze start")
        self._scan_imports_for_positive_signals()
        if self.tree is not None:
            self.visit(self.tree)
        else:
            logger.warning("PythonDetector: AST parse failed; using regex fallback")
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

    def _loop_depth(self, node: ast.AST) -> int:
        depth = 0
        parent = getattr(node, "parent", None)
        while parent is not None:
            if isinstance(parent, (ast.For, ast.While, ast.AsyncFor)):
                depth += 1
            parent = getattr(parent, "parent", None)
        return depth

    def generic_visit(self, node: ast.AST) -> None:
        for child in ast.iter_child_nodes(node):
            setattr(child, "parent", node)
        super().generic_visit(node)

    # ---------- Nested loop detection ----------
    def visit_For(self, node: ast.For) -> None:
        self._check_nested_loop(node)
        self.generic_visit(node)

    def visit_While(self, node: ast.While) -> None:
        self._check_nested_loop(node)
        self.generic_visit(node)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        self._check_nested_loop(node)
        self.generic_visit(node)

    def _check_nested_loop(self, outer: ast.AST) -> None:
        """Report once if any loop contains another loop (O(n²) risk)."""
        if self._nested_loop_reported:
            return
        for child in ast.walk(outer):
            if child is not outer and isinstance(child, (ast.For, ast.While, ast.AsyncFor)):
                self._issue(
                    rule="Nested loop (O(n²) risk)",
                    message=(
                        "Nested loops detected. This can lead to O(n²) or worse complexity. "
                        "Consider vectorizing with NumPy or restructuring the algorithm."
                    ),
                    penalty=6,
                )
                self._nested_loop_reported = True
                break

    # ---------- Call visitor ----------
    def visit_Call(self, node: ast.Call) -> None:
        func_name = self._qualname(node.func)
        in_loop = self._in_loop(node)

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
                message=f"Avoid calling `{func_name}` inside loops. Batch or hoist outside.",
                penalty=8,
            )

        if in_loop and func_name == "re.compile":
            self._issue(
                rule="Regex compile in loop",
                message="Move re.compile outside the loop and reuse the pattern.",
                penalty=10,
            )

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
            if isinstance(node.value, (ast.List, ast.Set, ast.Dict)):
                self._issue(
                    rule="Container allocation inside loop",
                    message="Avoid allocating lists/sets/dicts in loops; reuse or preallocate.",
                    penalty=7,
                )
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        if self._in_loop(node) and isinstance(node.op, ast.Add):
            if isinstance(node.target, ast.Name) and isinstance(node.value, (ast.Constant, ast.JoinedStr)):
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
        self.res.issues.append({"rule": rule, "message": message, "penalty": penalty})

    def _regex_fallback(self) -> None:
        text = self.code
        if re.search(r"\bprint\s*\(", text):
            self._issue("print usage", "Printing can be slow in hot paths.", 4)


# ---------------------------------------------------------------------------
# Java detector — uses javalang AST when available, regex fallback otherwise
# ---------------------------------------------------------------------------

_JAVA_LOOP_TYPES: Tuple = ()  # set after import guard below


def _java_ast_analyze(code: str) -> Optional[Dict]:
    """Return {issues, positive_signals} using javalang AST, or None on failure."""
    if not _JAVALANG:
        return None

    import javalang  # already confirmed importable

    LOOP_TYPES = (
        javalang.tree.ForStatement,   # covers both regular and enhanced for-each
        javalang.tree.WhileStatement,
        javalang.tree.DoStatement,
    )

    try:
        tree = javalang.parse.parse(code)
    except Exception as exc:
        logger.info("javalang: parse failed (%s); falling back to regex", exc)
        return None

    issues: List[Dict] = []
    positive_signals: List[str] = []
    seen_rules: set = set()

    def add_issue(rule: str, message: str, penalty: int) -> None:
        if rule not in seen_rules:
            seen_rules.add(rule)
            issues.append({"rule": rule, "message": message, "penalty": penalty})

    def in_loop(path) -> bool:
        return any(isinstance(p, LOOP_TYPES) for p in path)

    # --- Positive library imports ---
    POSITIVE_IMPORTS = [
        ("com.lmax.disruptor", "LMAX Disruptor (ring buffer)"),
        ("org.agrona", "Agrona (low-latency primitives)"),
        ("io.aeron", "Aeron (IPC / media driver)"),
        ("net.openhft.chronicle", "Chronicle (zero-GC queues/map)"),
        ("io.netty", "Netty (event-driven NIO)"),
        ("org.openjdk.jmh", "JMH (microbenchmarking)"),
        ("java.util.concurrent.atomic", "java.util.concurrent.atomic (lock-free)"),
        ("java.nio", "java.nio (non-blocking I/O)"),
    ]
    if tree.imports:
        for imp in tree.imports:
            imp_path = imp.path or ""
            for lib, label in POSITIVE_IMPORTS:
                if lib in imp_path and label not in positive_signals:
                    positive_signals.append(label)

    # --- Object allocations inside loops (GC pressure) ---
    for path, node in tree.filter(javalang.tree.ClassCreator):
        if in_loop(path):
            type_name = node.type.name if node.type else "Object"
            add_issue(
                rule=f"Allocation in loop: new {type_name}()",
                message=(
                    f"`new {type_name}()` inside a loop allocates heap objects on every iteration. "
                    "Consider pre-allocating, using object pools, or reusing instances."
                ),
                penalty=9,
            )

    # --- Problematic method calls inside loops ---
    BAD_METHODS = {
        "println":  ("System.out.println in loop",   12, "Avoid System.out.println in hot loops — it blocks on synchronized I/O."),
        "print":    ("System.out.print in loop",     12, "Avoid System.out.print in hot loops — it blocks on synchronized I/O."),
        "sleep":    ("Thread.sleep in loop",         10, "Thread.sleep inside a loop adds artificial latency; use timed waits or scheduling."),
        "format":   ("String.format in loop",         7, "String.format is slow due to reflection; prefer StringBuilder in loops."),
        "toString": ("toString() in loop",            5, "Repeated toString() calls in loops can be expensive; cache the result."),
        "valueOf":  ("String.valueOf in loop",         5, "String.valueOf in tight loops creates unnecessary String objects."),
    }
    for path, node in tree.filter(javalang.tree.MethodInvocation):
        if in_loop(path) and node.member in BAD_METHODS:
            rule, penalty, msg = BAD_METHODS[node.member]
            add_issue(rule=rule, message=msg, penalty=penalty)

    # --- synchronized blocks inside loops ---
    for path, node in tree.filter(javalang.tree.SynchronizedStatement):
        if in_loop(path):
            add_issue(
                rule="synchronized block in loop",
                message=(
                    "A synchronized block inside a loop serializes threads on every iteration. "
                    "Move locking outside the loop or switch to lock-free data structures (LongAdder, AtomicReference)."
                ),
                penalty=11,
            )

    # --- Positive usage signals ---
    POSITIVE_CALLS = {
        "allocateDirect": "Direct ByteBuffer (off-heap)",
        "newDirectByteBuffer": "Direct ByteBuffer (off-heap)",
    }
    POSITIVE_CREATORS = {
        "LongAdder":       "LongAdder (reduced contention counter)",
        "LongAccumulator": "LongAccumulator (custom reduce)",
        "AtomicLong":      "AtomicLong (CAS-based counter)",
    }
    for _, node in tree.filter(javalang.tree.MethodInvocation):
        if node.member in POSITIVE_CALLS and POSITIVE_CALLS[node.member] not in positive_signals:
            positive_signals.append(POSITIVE_CALLS[node.member])
    for _, node in tree.filter(javalang.tree.ClassCreator):
        if node.type and node.type.name in POSITIVE_CREATORS:
            label = POSITIVE_CREATORS[node.type.name]
            if label not in positive_signals:
                positive_signals.append(label)

    logger.info("javalang: issues=%d positives=%d", len(issues), len(positive_signals))
    return {"issues": issues, "positive_signals": positive_signals}


class JavaDetector:
    """Java latency detector — javalang AST when available, regex fallback."""

    POSITIVE_IMPORTS_RE = [
        (r"\bimport\s+com\.lmax\.disruptor\b", "LMAX Disruptor (ring buffer)"),
        (r"\bimport\s+org\.agrona\b", "Agrona (low-latency primitives)"),
        (r"\bimport\s+io\.aeron\b", "Aeron (media driver / IPC)"),
        (r"\bimport\s+net\.openhft\.chronicle\b", "Chronicle (zero-GC queues/map)"),
        (r"\bimport\s+io\.netty\b", "Netty (event-driven NIO)"),
        (r"\bimport\s+org\.openjdk\.jmh\b", "JMH (microbenchmarking)"),
    ]
    NEGATIVE_PATTERNS_RE = [
        (r"System\.out\.println\s*\(", 12, "Avoid System.out in hot paths; buffer or disable."),
        (r"new\s+\w+\s*\(.*\)\s*;",    8,  "Object allocation may pressure GC; consider reuse/pooling."),
        (r"synchronized\s*\(",         10, "Synchronization in hot paths can throttle throughput."),
        (r"String\s*\+\s*\w|\w\s*\+\s*String", 6, "String concatenation; prefer StringBuilder."),
        (r"Thread\.sleep\s*\(",        8,  "Sleeping in critical paths adds latency."),
    ]
    POSITIVE_CALLS_RE = [
        (r"LongAdder",              "LongAdder (reduced contention counter)"),
        (r"VarHandle",              "VarHandle (low-level memory ops)"),
        (r"ByteBuffer\.allocateDirect", "Direct ByteBuffer (off-heap)"),
        (r"Epoll|KQueue",           "Native transport (epoll/kqueue)"),
    ]

    def __init__(self, code: str) -> None:
        self.code = code

    def analyze(self) -> DetectorResult:
        logger.info("JavaDetector: analyze start (javalang=%s)", _JAVALANG)

        ast_result = _java_ast_analyze(self.code)
        if ast_result is not None:
            res = DetectorResult()
            res.issues = ast_result["issues"]
            res.positive_signals = ast_result["positive_signals"]
            logger.info(
                "JavaDetector: AST path done (issues=%d, positives=%d)",
                len(res.issues), len(res.positive_signals),
            )
            return res

        # --- Regex fallback ---
        logger.info("JavaDetector: using regex fallback")
        res = DetectorResult()
        text = self.code
        for pat, label in self.POSITIVE_IMPORTS_RE:
            if re.search(pat, text):
                res.positive_signals.append(label)
        for pat, label in self.POSITIVE_CALLS_RE:
            if re.search(pat, text):
                res.positive_signals.append(label)
        for pat, penalty, msg in self.NEGATIVE_PATTERNS_RE:
            if re.search(pat, text):
                res.issues.append({"rule": "Java pattern", "message": msg, "penalty": penalty})
        logger.info(
            "JavaDetector: regex fallback done (issues=%d, positives=%d)",
            len(res.issues), len(res.positive_signals),
        )
        return res


# ---------------------------------------------------------------------------
# C++ detector — tree-sitter AST when available, regex fallback otherwise
# ---------------------------------------------------------------------------

def _cpp_walk(node, parents=None):
    """Yield (node, parents_list) for every node in the tree."""
    if parents is None:
        parents = []
    yield node, parents
    child_parents = parents + [node]
    for child in node.children:
        yield from _cpp_walk(child, child_parents)


def _cpp_ast_analyze(code: str) -> Optional[Dict]:
    """Return {issues, positive_signals} via tree-sitter C++ AST, or None on failure."""
    if not _TREE_SITTER_CPP:
        return None

    try:
        from tree_sitter import Language, Parser as TSParser
        import tree_sitter_cpp as tscpp
        language = Language(tscpp.language())
        parser = TSParser(language)
        tree = parser.parse(code.encode("utf-8", errors="replace"))
    except Exception as exc:
        logger.info("tree-sitter C++: parse failed (%s); falling back to regex", exc)
        return None

    LOOP_TYPES = {
        "for_statement",
        "while_statement",
        "do_statement",
        "for_range_loop",         # range-based for
    }

    def in_loop(parents) -> bool:
        return any(p.type in LOOP_TYPES for p in parents)

    def node_text(n) -> str:
        try:
            return n.text.decode("utf-8", errors="replace")
        except Exception:
            return ""

    issues: List[Dict] = []
    positive_signals: List[str] = []
    seen_rules: set = set()

    def add_issue(rule: str, message: str, penalty: int) -> None:
        if rule not in seen_rules:
            seen_rules.add(rule)
            issues.append({"rule": rule, "message": message, "penalty": penalty})

    # Positive include patterns (checked on include string nodes)
    POSITIVE_INCLUDES = [
        ("boost/lockfree/",  "Boost lockfree structures"),
        ("folly/",           "Facebook Folly performance primitives"),
        ("absl/",            "Abseil containers/arenas"),
        ("memory_resource",  "std::pmr polymorphic allocators"),
        ("tbb/",             "Intel TBB (task-based parallelism)"),
        ("immintrin.h",      "AVX/SSE SIMD intrinsics"),
        ("xmmintrin.h",      "SSE SIMD intrinsics"),
    ]

    for node, parents in _cpp_walk(tree.root_node):
        txt = node_text(node)

        # --- Positive signals from #include strings ---
        if node.type in ("system_lib_string", "string_literal"):
            for pattern, label in POSITIVE_INCLUDES:
                if pattern in txt and label not in positive_signals:
                    positive_signals.append(label)

        # --- new expression in loop ---
        if node.type == "new_expression" and in_loop(parents):
            add_issue(
                rule="Dynamic allocation in loop (new)",
                message=(
                    "`new` inside a hot loop causes heap fragmentation and latency spikes. "
                    "Use object pools, placement new, or stack allocation instead."
                ),
                penalty=10,
            )

        # --- malloc/calloc/realloc in loop ---
        if node.type == "call_expression" and in_loop(parents):
            func_node = node.child_by_field_name("function")
            func_txt = node_text(func_node) if func_node else ""
            if func_txt in ("malloc", "calloc", "realloc"):
                add_issue(
                    rule=f"{func_txt}() in loop",
                    message=(
                        f"`{func_txt}()` in a hot loop is expensive. "
                        "Pre-allocate buffers outside the loop."
                    ),
                    penalty=10,
                )

        # --- std::cout in loop ---
        if node.type in ("qualified_identifier", "identifier") and in_loop(parents):
            if "cout" in txt or "cerr" in txt:
                stream = "cerr" if "cerr" in txt else "cout"
                add_issue(
                    rule=f"std::{stream} in loop",
                    message=(
                        f"`std::{stream}` inside a loop causes synchronised I/O stalls. "
                        "Use a logging framework with async/buffered output or remove entirely."
                    ),
                    penalty=12,
                )

        # --- shared_ptr in loop (atomic refcount overhead) ---
        if node.type == "template_type" and in_loop(parents):
            if "shared_ptr" in txt:
                add_issue(
                    rule="shared_ptr in loop",
                    message=(
                        "`shared_ptr` uses atomic reference counting on every copy/destroy. "
                        "In loops this creates contention. Prefer raw pointers or `unique_ptr`."
                    ),
                    penalty=7,
                )

        # --- std::function in loop (type erasure overhead) ---
        if node.type == "template_type" and in_loop(parents):
            if "std::function" in txt or (
                node.child_count > 0 and "function" in txt and "std" in txt
            ):
                add_issue(
                    rule="std::function in loop",
                    message=(
                        "`std::function` type-erasure heap-allocates a closure. "
                        "Replace with templates, lambdas captured by value, or function pointers."
                    ),
                    penalty=6,
                )

        # --- virtual dispatch in loop ---
        if node.type == "virtual_function_specifier" and in_loop(parents):
            add_issue(
                rule="Virtual dispatch in loop",
                message=(
                    "Virtual function calls in tight loops prevent inlining and hurt branch prediction. "
                    "Use CRTP, templates, or devirtualization where possible."
                ),
                penalty=5,
            )

        # --- Positive: SIMD intrinsic calls ---
        if node.type == "call_expression":
            func_node = node.child_by_field_name("function")
            func_txt = node_text(func_node) if func_node else ""
            if func_txt.startswith("_mm") or func_txt.startswith("__builtin_ia32"):
                label = "SIMD intrinsics (manual vectorisation)"
                if label not in positive_signals:
                    positive_signals.append(label)

    logger.info("tree-sitter C++: issues=%d positives=%d", len(issues), len(positive_signals))
    return {"issues": issues, "positive_signals": positive_signals}


class CppDetector:
    """C++ latency detector — tree-sitter AST when available, regex fallback."""

    POSITIVE_INCLUDES_RE = [
        (r"#include\s*<boost/lockfree/",  "Boost lockfree structures"),
        (r"#include\s*<folly/",           "Facebook Folly performance primitives"),
        (r"#include\s*<absl/",            "Abseil containers/arenas"),
        (r"#include\s*<memory_resource>", "std::pmr polymorphic allocators"),
    ]
    NEGATIVE_PATTERNS_RE = [
        (r"std::cout\s*<<",           12, "std::cout in hot paths causes I/O stalls."),
        (r"new\s+\w+\s*\(|malloc\s*\(", 10, "Dynamic allocation in loops increases latency/fragmentation."),
        (r"std::shared_ptr\s*<",        6, "shared_ptr has atomic refcount; avoid in hot loops."),
        (r"std::function\s*<",          6, "std::function type erasure incurs overhead; avoid in loops."),
        (r"virtual\s+\w+\s*\(",         4, "Virtual dispatch in hot loops can hurt branch prediction."),
    ]

    def __init__(self, code: str) -> None:
        self.code = code

    def analyze(self) -> DetectorResult:
        logger.info("CppDetector: analyze start (tree-sitter=%s)", _TREE_SITTER_CPP)

        ast_result = _cpp_ast_analyze(self.code)
        if ast_result is not None:
            res = DetectorResult()
            res.issues = ast_result["issues"]
            res.positive_signals = ast_result["positive_signals"]
            logger.info(
                "CppDetector: AST path done (issues=%d, positives=%d)",
                len(res.issues), len(res.positive_signals),
            )
            return res

        # --- Regex fallback ---
        logger.info("CppDetector: using regex fallback")
        res = DetectorResult()
        text = self.code
        for pat, label in self.POSITIVE_INCLUDES_RE:
            if re.search(pat, text):
                res.positive_signals.append(label)
        for pat, penalty, msg in self.NEGATIVE_PATTERNS_RE:
            if re.search(pat, text):
                res.issues.append({"rule": "C++ pattern", "message": msg, "penalty": penalty})
        logger.info(
            "CppDetector: regex fallback done (issues=%d, positives=%d)",
            len(res.issues), len(res.positive_signals),
        )
        return res
