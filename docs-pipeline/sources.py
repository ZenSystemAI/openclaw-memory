"""Documentation source definitions for the docs-ingest pipeline.

Each source is a class that knows how to fetch its documentation files.
ALL_SOURCES maps source names to their classes.

To add a new source:
1. Create a class with a fetch_docs() method
2. fetch_docs() returns a list of DocFile(path, url, content)
3. Add it to ALL_SOURCES at the bottom of this file
"""
import glob
import logging
import os
import subprocess
from dataclasses import dataclass

from config import CLONE_DIR

log = logging.getLogger(__name__)


@dataclass
class DocFile:
    """A single documentation file ready for chunking."""
    path: str       # Relative path within the repo/source
    url: str        # Public URL for this doc (or empty string)
    content: str    # Raw file content (markdown or yaml)


class GitDocSource:
    """Fetch docs from a git repository.

    Args:
        name: Source identifier (used as filter key in Qdrant).
        repo_url: Git clone URL.
        glob_pattern: Glob pattern for doc files relative to repo root
                      (e.g. "docs/**/*.md").
        url_template: Template to build a public URL from the file path.
                      Use {path} as placeholder. Leave empty if no public URL.
        branch: Git branch to clone. Default: "main".
        sparse_dirs: Optional list of directories for sparse checkout
                     (faster for large repos). If empty, full clone.
    """

    def __init__(
        self,
        name: str,
        repo_url: str,
        glob_pattern: str,
        url_template: str = "",
        branch: str = "main",
        sparse_dirs: list[str] | None = None,
    ):
        self.name = name
        self.repo_url = repo_url
        self.glob_pattern = glob_pattern
        self.url_template = url_template
        self.branch = branch
        self.sparse_dirs = sparse_dirs or []

    def fetch_docs(self) -> list[DocFile]:
        """Clone/pull the repo and return matching doc files."""
        repo_dir = os.path.join(CLONE_DIR, self.name)

        if os.path.isdir(os.path.join(repo_dir, ".git")):
            log.info("Pulling latest for %s", self.name)
            subprocess.run(
                ["git", "-C", repo_dir, "pull", "--ff-only"],
                capture_output=True, timeout=120,
            )
        else:
            log.info("Cloning %s from %s", self.name, self.repo_url)
            cmd = ["git", "clone", "--depth", "1", "--branch", self.branch]
            if self.sparse_dirs:
                cmd += ["--filter=blob:none", "--sparse"]
            cmd += [self.repo_url, repo_dir]
            subprocess.run(cmd, capture_output=True, timeout=300, check=True)

            if self.sparse_dirs:
                subprocess.run(
                    ["git", "-C", repo_dir, "sparse-checkout", "set"] + self.sparse_dirs,
                    capture_output=True, timeout=60, check=True,
                )

        # Find matching files
        pattern = os.path.join(repo_dir, self.glob_pattern)
        matches = sorted(glob.glob(pattern, recursive=True))
        log.info("Found %d files matching %s", len(matches), self.glob_pattern)

        docs = []
        for filepath in matches:
            rel_path = os.path.relpath(filepath, repo_dir)
            try:
                with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
            except OSError as e:
                log.warning("Could not read %s: %s", filepath, e)
                continue

            if not content.strip():
                continue

            url = ""
            if self.url_template:
                url = self.url_template.format(path=rel_path.replace("\\", "/"))

            docs.append(DocFile(path=rel_path, url=url, content=content))

        return docs


class LocalDocSource:
    """Fetch docs from a local directory (no git).

    Args:
        name: Source identifier.
        local_path: Absolute path to the docs directory.
        glob_pattern: Glob pattern relative to local_path.
        url_template: Optional URL template ({path} placeholder).
    """

    def __init__(
        self,
        name: str,
        local_path: str,
        glob_pattern: str,
        url_template: str = "",
    ):
        self.name = name
        self.local_path = os.path.expanduser(local_path)
        self.glob_pattern = glob_pattern
        self.url_template = url_template

    def fetch_docs(self) -> list[DocFile]:
        """Read matching files from the local directory."""
        if not os.path.isdir(self.local_path):
            log.error("Local path does not exist: %s", self.local_path)
            return []

        pattern = os.path.join(self.local_path, self.glob_pattern)
        matches = sorted(glob.glob(pattern, recursive=True))
        log.info("Found %d files matching %s in %s", len(matches), self.glob_pattern, self.local_path)

        docs = []
        for filepath in matches:
            rel_path = os.path.relpath(filepath, self.local_path)
            try:
                with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
            except OSError as e:
                log.warning("Could not read %s: %s", filepath, e)
                continue

            if not content.strip():
                continue

            url = ""
            if self.url_template:
                url = self.url_template.format(path=rel_path.replace("\\", "/"))

            docs.append(DocFile(path=rel_path, url=url, content=content))

        return docs


# ---------------------------------------------------------------------------
# ALL_SOURCES — add your documentation sources here
# ---------------------------------------------------------------------------
# Each entry maps a source name (used with --source) to a callable that
# returns a source instance. The name must be lowercase.
#
# Example git source:
#
#   "n8n": lambda: GitDocSource(
#       name="n8n",
#       repo_url="https://github.com/n8n-io/n8n-docs.git",
#       glob_pattern="docs/**/*.md",
#       url_template="https://docs.n8n.io/{path}",
#       branch="main",
#       sparse_dirs=["docs"],
#   ),
#
# Example local source:
#
#   "openclaw": lambda: LocalDocSource(
#       name="openclaw",
#       local_path="~/.openclaw/docs",
#       glob_pattern="**/*.md",
#   ),
#
# To add a new source:
# 1. Add an entry below with a unique lowercase name
# 2. Run: python3 docs-ingest.py --source <name> --mode full
# 3. Verify: python3 docs-ingest.py --stats

ALL_SOURCES: dict[str, callable] = {
    # Uncomment and configure the sources you want to ingest:
    #
    # "n8n": lambda: GitDocSource(
    #     name="n8n",
    #     repo_url="https://github.com/n8n-io/n8n-docs.git",
    #     glob_pattern="docs/**/*.md",
    #     url_template="https://docs.n8n.io/{path}",
    #     branch="main",
    #     sparse_dirs=["docs"],
    # ),
    #
    # "baserow": lambda: GitDocSource(
    #     name="baserow",
    #     repo_url="https://github.com/bram2w/baserow.git",
    #     glob_pattern="docs/**/*.md",
    #     url_template="https://baserow.io/docs/{path}",
    #     branch="develop",
    #     sparse_dirs=["docs"],
    # ),
    #
    # "wordpress": lambda: GitDocSource(
    #     name="wordpress",
    #     repo_url="https://github.com/WordPress/wordpress-develop.git",
    #     glob_pattern="src/wp-includes/rest-api/**/*.php",
    #     url_template="https://developer.wordpress.org/rest-api/",
    #     branch="trunk",
    #     sparse_dirs=["src/wp-includes/rest-api"],
    # ),
    #
    # "openclaw": lambda: LocalDocSource(
    #     name="openclaw",
    #     local_path="~/.openclaw/docs",
    #     glob_pattern="**/*.md",
    # ),
}
