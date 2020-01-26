import contextlib
import os
import subprocess
import tempfile
import textwrap
from pathlib import Path
from unittest import TestCase
import git_cleanup as cleanup
import logging

logger = logging.getLogger("TEST")
logger.setLevel(level=os.getenv("TEST_LOG_LEVEL", "WARNING"))


@contextlib.contextmanager
def fixture_context(fixture_setup):
    pwd = os.getcwd()
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            os.chdir(tmpdir)
            input = fixture_setup.encode()
            with subprocess.Popen(
                ["/usr/bin/env", "bash", "-xe", "-"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT) as process:
                process.stdin.write(input)
                process.stdin.close()
                for line in process.stdout.readlines():
                    logger.debug(line.decode().rstrip('\n'))
            os.chdir(Path(tmpdir, "local"))
            yield
    finally:
        os.chdir(pwd)


def with_fixture(fixture):
    # Set an triangular workflow
    prologue = textwrap.dedent("""
    shopt -s expand_aliases
    within() {
        pushd $1 > /dev/null
        bash -x -
        popd > /dev/null
    }
    alias upstream='within upstream'
    alias origin='within origin'
    alias local='within local'
    """)

    epilogue = textwrap.dedent("""
    local <<< "git remote update --prune"
    """)

    def decorator(func):
        def wrapper(self, *args):
            if self.fixture_init:
                final_fixture = prologue + textwrap.dedent(self.fixture_init) + textwrap.dedent(fixture) + epilogue
            else:
                final_fixture = prologue + textwrap.dedent(fixture) + epilogue
            with fixture_context(final_fixture):
                func(self, *args)

        return wrapper

    return decorator


class TestSimplePullRequestWorkflow(TestCase):
    fixture_init = """
    git init origin
    origin <<EOF
        git config user.name "Origin Test"
        git config user.email "origin@test"
        echo "Hello World!" > README.md
        git add README.md
        git commit -m "Initial commit"
    EOF
    git clone origin local
    local <<EOF
        git config user.name "Local Test"
        git config user.email "local@test"
        git config remote.pushdefault origin
        git config push.default current
    EOF
    """

    @with_fixture("""
    local <<EOF
        git checkout -b feature 
        touch awesome-patch
        git add awesome-patch
        git commit -m "Awesome patch"
        git push -u origin
    EOF
    origin <<EOF
        git checkout master
        git merge feature
        git branch -d feature
    EOF
    """)
    def test_accepted(self):
        to_remove = cleanup.get_branches_to_remove("origin/master")
        self.assertEqual(to_remove, {
            "local": {"feature"},
            "remotes": {},
        })

    @with_fixture("""
        local <<EOF
            git checkout -b feature 
            touch awesome-patch
            git add awesome-patch
            git commit -m "Awesome patch"
            git push -u origin
        EOF
        origin <<EOF
            git checkout master
            git merge feature
        EOF
        """)
    def test_accepted_but_forgot_to_delete(self):
        to_remove = cleanup.get_branches_to_remove("origin/master")
        self.assertEqual(to_remove, {
            "local": {"feature"},
            "remotes": {
                "origin": { "feature" }
            }
        })

    @with_fixture("""
        local <<EOF
            git checkout -b feature 
            touch awesome-patch
            git add awesome-patch
            git commit -m "Awesome patch"
            git push -u origin
        EOF
        origin <<EOF
            git branch -D feature
        EOF
        """)
    def test_rejected(self):
        to_remove = cleanup.get_branches_to_remove("origin/master")
        self.assertEqual(to_remove, {
            "local": {"feature"},
            "remotes": {},
        })

    @with_fixture("""
        local <<EOF
            git checkout -b feature 
            touch awesome-patch
            git add awesome-patch
            git commit -m "Awesome patch"
            git push -u origin
        EOF
        """)
    def test_rejected_but_forgot_to_delete(self):
        to_remove = cleanup.get_branches_to_remove("origin/master")
        self.assertEqual(to_remove, {
            "local": set(),
            "remotes": {},
        })


class TestSimpleTriangularPullRequestWorkflow(TestCase):
    fixture_init = """
    git init upstream
    upstream <<EOF
        git config user.name "Upstream Test"
        git config user.email "upstream@test"
        echo "Hello World!" > README.md
        git add README.md
        git commit -m "Initial commit"
    EOF
    git clone upstream origin -o upstream
    origin <<EOF
        git config user.name "Origin Test"
        git config user.email "origin@test"
        git config remote.pushdefault upstream
        git config push.default current
    EOF
    git clone origin local
    local <<EOF
        git config user.name "Local Test"
        git config user.email "local@test"
        git config remote.pushdefault origin
        git config push.default current
        git remote add upstream ../upstream
        git fetch upstream
        git branch -u upstream/master master
    EOF
    """

    @with_fixture("""
        local <<EOF
            git checkout -b feature 
            touch awesome-patch
            git add awesome-patch
            git commit -m "Awesome patch"
            git push -u origin
        EOF
        origin <<EOF
            git push upstream feature:refs/pull/1/head
        EOF
        upstream <<EOF
            git merge refs/pull/1/head
        EOF
        # clicked delete branch button 
        origin <<EOF
            git branch -D feature
        EOF
        """)
    def test_accepted(self):
        to_remove = cleanup.get_branches_to_remove("upstream/master")
        self.assertEqual(to_remove, {
            "local": {"feature"},
            "remotes": {},
        })

    @with_fixture("""
        local <<EOF
            git checkout -b feature 
            touch awesome-patch
            git add awesome-patch
            git commit -m "Awesome patch"
            git push -u origin
        EOF
        origin <<EOF
            git push upstream feature:refs/pull/1/head
        EOF
        upstream <<EOF
            git merge refs/pull/1/head
        EOF
        """)
    def test_accepted_but_forgot_to_delete(self):
        to_remove = cleanup.get_branches_to_remove("upstream/master")
        self.assertEqual(to_remove, {
            "local": {"feature"},
            "remotes": {
                "origin": {"feature"}
            }
        })

    @with_fixture("""
        local <<EOF
            git checkout -b feature 
            touch awesome-patch
            git add awesome-patch
            git commit -m "Awesome patch"
            git push -u origin
        EOF
        origin <<EOF
            git push upstream feature:refs/pull/1/head
            
            git branch -D feature
        EOF
        """)
    def test_rejected(self):
        to_remove = cleanup.get_branches_to_remove("upstream/master")
        self.assertEqual(to_remove, {
            "local": {"feature"},
            "remotes": {}
        })

    @with_fixture("""
        local <<EOF
            git checkout -b feature 
            touch awesome-patch
            git add awesome-patch
            git commit -m "Awesome patch"
            git push -u origin
        EOF
        origin <<EOF
            git push upstream feature:refs/pull/1/head
        EOF
        """)
    def test_rejected_but_forgot_to_dele(self):
        to_remove = cleanup.get_branches_to_remove("upstream/master")
        self.assertEqual(to_remove, {
            "local": set(),
            "remotes": {}
        })
