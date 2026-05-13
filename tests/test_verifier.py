"""Unit tests for pr_reviewer.verifier and pr_reviewer.diff.extract_changed_files.

Phase 2 of v0.5.0 lands extract_changed_files (in diff.py); the rest of this
file is filled in by Phase 3 once verifier.py exists.
"""
from __future__ import annotations

import pytest

from pr_reviewer.diff import extract_changed_files


# ---------- extract_changed_files ----------

ADDED_FILE_DIFF = """\
diff --git a/src/foo.py b/src/foo.py
new file mode 100644
index 0000000..abc1234
--- /dev/null
+++ b/src/foo.py
@@ -0,0 +1,3 @@
+def foo():
+    return 1
+
"""

MODIFIED_FILE_DIFF = """\
diff --git a/src/bar.py b/src/bar.py
index abc..def 100644
--- a/src/bar.py
+++ b/src/bar.py
@@ -10,3 +10,4 @@ def bar():
     x = 1
     y = 2
+    z = 3
     return x + y
"""

DELETED_FILE_DIFF = """\
diff --git a/src/baz.py b/src/baz.py
deleted file mode 100644
index abc..0000000
--- a/src/baz.py
+++ /dev/null
@@ -1,3 +0,0 @@
-def baz():
-    return 0
-
"""

MULTIPLE_FILES_DIFF = ADDED_FILE_DIFF + "\n" + MODIFIED_FILE_DIFF + "\n" + DELETED_FILE_DIFF


def test_extract_changed_files_added():
    assert extract_changed_files(ADDED_FILE_DIFF) == {"src/foo.py"}


def test_extract_changed_files_modified():
    assert extract_changed_files(MODIFIED_FILE_DIFF) == {"src/bar.py"}


def test_extract_changed_files_deleted_ignored():
    """Deleted files have `+++ /dev/null` and should NOT appear in the set
    — the verifier only checks findings against post-change file paths."""
    assert extract_changed_files(DELETED_FILE_DIFF) == set()


def test_extract_changed_files_multiple():
    """A combined diff lists every post-change file path (added + modified)."""
    result = extract_changed_files(MULTIPLE_FILES_DIFF)
    assert result == {"src/foo.py", "src/bar.py"}
    assert "src/baz.py" not in result
