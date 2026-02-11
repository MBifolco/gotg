"""Tests for per-file diff viewer in ContentViewer."""

import pytest

from gotg.tui.widgets.content_viewer import ContentViewer, parse_diff_files

from textual.widgets import Collapsible, Static


# ── parse_diff_files unit tests ──────────────────────────────


MULTI_FILE_DIFF = """\
diff --git a/src/main.py b/src/main.py
index abc123..def456 100644
--- a/src/main.py
+++ b/src/main.py
@@ -1,3 +1,4 @@
 import os
+import sys

 def main():
diff --git a/src/utils.py b/src/utils.py
index 111111..222222 100644
--- a/src/utils.py
+++ b/src/utils.py
@@ -5,3 +5,6 @@
 def helper():
     pass
+
+def new_helper():
+    return True
diff --git a/tests/test_main.py b/tests/test_main.py
new file mode 100644
--- /dev/null
+++ b/tests/test_main.py
@@ -0,0 +1,5 @@
+import pytest
+
+def test_main():
+    assert True
"""


def test_parse_multi_file_diff():
    """Parses a multi-file diff into per-file sections."""
    files = parse_diff_files(MULTI_FILE_DIFF)
    assert len(files) == 3
    assert files[0][0] == "src/main.py"
    assert files[1][0] == "src/utils.py"
    assert files[2][0] == "tests/test_main.py"


def test_parse_each_section_contains_full_diff():
    """Each section contains its complete diff hunks."""
    files = parse_diff_files(MULTI_FILE_DIFF)
    # First file section should contain its hunk
    assert "+import sys" in files[0][1]
    assert "+def new_helper" not in files[0][1]
    # Second file section
    assert "+def new_helper" in files[1][1]
    # Third file section
    assert "+import pytest" in files[2][1]


def test_parse_stat_only_returns_empty():
    """Stat-only output (no 'diff --git') returns empty list."""
    stat = " src/main.py | 2 +-\n 1 file changed, 1 insertion(+), 1 deletion(-)"
    assert parse_diff_files(stat) == []


def test_parse_empty_string():
    assert parse_diff_files("") == []


def test_parse_no_changes_text():
    assert parse_diff_files("(no changes)") == []


def test_parse_single_file_diff():
    diff = (
        "diff --git a/README.md b/README.md\n"
        "--- a/README.md\n"
        "+++ b/README.md\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n"
    )
    files = parse_diff_files(diff)
    assert len(files) == 1
    assert files[0][0] == "README.md"


def test_parse_missing_b_path():
    """Falls back to '(unknown file)' if b/ path missing."""
    diff = "diff --git a/src/foo.py\n+added line\n"
    files = parse_diff_files(diff)
    assert len(files) == 1
    assert files[0][0] == "(unknown file)"


# ── ContentViewer.show_diff integration tests ────────────────


@pytest.mark.asyncio
async def test_show_diff_multi_file_creates_collapsibles():
    """Multi-file diff creates one Collapsible per file."""
    from textual.app import App

    class TestApp(App):
        def compose(self):
            yield ContentViewer(id="cv")

    app = TestApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        cv = app.query_one("#cv", ContentViewer)
        cv.show_diff("test-branch", MULTI_FILE_DIFF)
        await pilot.pause()

        collapsibles = cv.query(Collapsible)
        assert len(collapsibles) == 3


@pytest.mark.asyncio
async def test_show_diff_first_expanded_rest_collapsed():
    """First file expanded, rest collapsed."""
    from textual.app import App

    class TestApp(App):
        def compose(self):
            yield ContentViewer(id="cv")

    app = TestApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        cv = app.query_one("#cv", ContentViewer)
        cv.show_diff("test-branch", MULTI_FILE_DIFF)
        await pilot.pause()

        collapsibles = list(cv.query(Collapsible))
        assert not collapsibles[0].collapsed
        assert collapsibles[1].collapsed
        assert collapsibles[2].collapsed


@pytest.mark.asyncio
async def test_show_diff_collapsible_titles_are_filenames():
    """Collapsible titles match parsed filenames."""
    from textual.app import App

    class TestApp(App):
        def compose(self):
            yield ContentViewer(id="cv")

    app = TestApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        cv = app.query_one("#cv", ContentViewer)
        cv.show_diff("test-branch", MULTI_FILE_DIFF)
        await pilot.pause()

        collapsibles = list(cv.query(Collapsible))
        assert collapsibles[0].title == "src/main.py"
        assert collapsibles[1].title == "src/utils.py"
        assert collapsibles[2].title == "tests/test_main.py"


@pytest.mark.asyncio
async def test_show_diff_stat_only_no_collapsibles():
    """Stat-only content shows as plain Static, no Collapsibles."""
    from textual.app import App

    class TestApp(App):
        def compose(self):
            yield ContentViewer(id="cv")

    app = TestApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        cv = app.query_one("#cv", ContentViewer)
        stat = " src/main.py | 2 +-\n 1 file changed"
        cv.show_diff("test-branch", stat)
        await pilot.pause()

        collapsibles = cv.query(Collapsible)
        assert len(collapsibles) == 0
        # Should have header + content Statics
        statics = cv.query(Static)
        assert len(statics) >= 2


@pytest.mark.asyncio
async def test_show_diff_has_header():
    """show_diff always includes a title header."""
    from textual.app import App

    class TestApp(App):
        def compose(self):
            yield ContentViewer(id="cv")

    app = TestApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        cv = app.query_one("#cv", ContentViewer)
        cv.show_diff("my-branch/layer-0", MULTI_FILE_DIFF)
        await pilot.pause()

        headers = cv.query(".cv-header")
        assert len(headers) == 1


@pytest.mark.asyncio
async def test_show_diff_single_file_one_collapsible():
    """Single-file diff creates one expanded Collapsible."""
    from textual.app import App

    class TestApp(App):
        def compose(self):
            yield ContentViewer(id="cv")

    diff = (
        "diff --git a/foo.py b/foo.py\n"
        "--- a/foo.py\n"
        "+++ b/foo.py\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n"
    )

    app = TestApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        cv = app.query_one("#cv", ContentViewer)
        cv.show_diff("branch", diff)
        await pilot.pause()

        collapsibles = list(cv.query(Collapsible))
        assert len(collapsibles) == 1
        assert not collapsibles[0].collapsed
        assert collapsibles[0].title == "foo.py"
