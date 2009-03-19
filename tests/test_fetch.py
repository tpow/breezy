# Copyright (C) 2009 Jelmer Vernooij <jelmer@samba.org>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

from dulwich.objects import (
    Blob,
    Tree,
    )
import os

from bzrlib import (
    knit,
    osutils,
    versionedfile,
    )
from bzrlib.bzrdir import (
    BzrDir,
    )
from bzrlib.inventory import (
    Inventory,
    )
from bzrlib.repository import (
    Repository,
    )
from bzrlib.tests import (
    TestCaseWithTransport,
    )
from bzrlib.transport import (
    get_transport,
    )

from bzrlib.plugins.git import (
    get_rich_root_format,
    )
from bzrlib.plugins.git.fetch import (
    BzrFetchGraphWalker,
    import_git_blob,
    import_git_tree,
    )
from bzrlib.plugins.git.mapping import (
    BzrGitMappingv1,
    default_mapping,
    )
from bzrlib.plugins.git.shamap import (
    DictGitShaMap,
    )
from bzrlib.plugins.git.tests import (
    GitBranchBuilder,
    run_git,
    )


class FetchGraphWalkerTests(TestCaseWithTransport):

    def setUp(self):
        TestCaseWithTransport.setUp(self)
        self.mapping = default_mapping

    def test_empty(self):
        tree = self.make_branch_and_tree("wt")
        graphwalker = BzrFetchGraphWalker(tree.branch.repository, self.mapping)
        self.assertEquals(None, graphwalker.next())


class LocalRepositoryFetchTests(TestCaseWithTransport):

    def make_git_repo(self, path):
        os.mkdir(path)
        os.chdir(path)
        run_git("init")
        os.chdir("..")

    def clone_git_repo(self, from_url, to_url):
        oldrepos = Repository.open(from_url)
        dir = BzrDir.create(to_url, get_rich_root_format())
        newrepos = dir.create_repository()
        oldrepos.copy_content_into(newrepos)
        return newrepos

    def test_empty(self):
        self.make_git_repo("d")
        newrepos = self.clone_git_repo("d", "f")
        self.assertEquals([], newrepos.all_revision_ids())

    def test_single_rev(self):
        self.make_git_repo("d")
        os.chdir("d")
        bb = GitBranchBuilder()
        bb.set_file("foobar", "foo\nbar\n", False)
        mark = bb.commit("Somebody <somebody@someorg.org>", "mymsg")
        gitsha = bb.finish()[mark]
        os.chdir("..")
        oldrepo = Repository.open("d")
        newrepo = self.clone_git_repo("d", "f")
        self.assertEquals([oldrepo.get_mapping().revision_id_foreign_to_bzr(gitsha)], newrepo.all_revision_ids())

    def test_executable(self):
        self.make_git_repo("d")
        os.chdir("d")
        bb = GitBranchBuilder()
        bb.set_file("foobar", "foo\nbar\n", True)
        bb.set_file("notexec", "foo\nbar\n", False)
        mark = bb.commit("Somebody <somebody@someorg.org>", "mymsg")
        gitsha = bb.finish()[mark]
        os.chdir("..")
        oldrepo = Repository.open("d")
        newrepo = self.clone_git_repo("d", "f")
        revid = oldrepo.get_mapping().revision_id_foreign_to_bzr(gitsha)
        tree = newrepo.revision_tree(revid)
        self.assertTrue(tree.has_filename("foobar"))
        self.assertEquals(True, tree.inventory[tree.path2id("foobar")].executable)
        self.assertTrue(tree.has_filename("notexec"))
        self.assertEquals(False, tree.inventory[tree.path2id("notexec")].executable)


class ImportObjects(TestCaseWithTransport):

    def setUp(self):
        super(ImportObjects, self).setUp()
        self._map = DictGitShaMap()
        self._mapping = BzrGitMappingv1()
        factory = knit.make_file_factory(True, versionedfile.PrefixMapper())
        self._texts = factory(self.get_transport('texts'))

    def test_import_blob_simple(self):
        blob = Blob.from_string("bar")
        inv = Inventory()
        inv.revision_id = "somerevid"
        import_git_blob(self._texts, self._mapping, "bla", blob, 
            inv, [], self._map, False)
        self.assertEquals(set([('bla', 'somerevid')]), self._texts.keys())
        self.assertEquals(self._texts.get_record_stream([('bla', 'somerevid')],
            "unordered", True).next().get_bytes_as("fulltext"), "bar")
        self.assertEquals(False, inv["bla"].executable)
        self.assertEquals("file", inv["bla"].kind)
        self.assertEquals("somerevid", inv["bla"].revision)
        self.assertEquals(osutils.sha_strings(["bar"]), inv["bla"].text_sha1)

    def test_import_tree_empty_root(self):
        inv = Inventory()
        inv.revision_id = "somerevid"
        tree = Tree()
        tree.serialize()
        import_git_tree(self._texts, self._mapping, "", tree, inv, [], 
            self._map, {}.__getitem__)
        self.assertEquals(set([("TREE_ROOT", 'somerevid')]), self._texts.keys())
        self.assertEquals(False, inv["TREE_ROOT"].executable)
        self.assertEquals("directory", inv["TREE_ROOT"].kind)
        self.assertEquals({}, inv["TREE_ROOT"].children)
        self.assertEquals("somerevid", inv["TREE_ROOT"].revision)
        self.assertEquals(None, inv["TREE_ROOT"].text_sha1)

    def test_import_tree_empty(self):
        inv = Inventory()
        inv.revision_id = "somerevid"
        tree = Tree()
        tree.serialize()
        import_git_tree(self._texts, self._mapping, "bla", tree, inv, [], 
            self._map, {}.__getitem__)
        self.assertEquals(set([("bla", 'somerevid')]), self._texts.keys())
        self.assertEquals("directory", inv["bla"].kind)
        self.assertEquals(False, inv["bla"].executable)
        self.assertEquals({}, inv["bla"].children)
        self.assertEquals("somerevid", inv["bla"].revision)
        self.assertEquals(None, inv["bla"].text_sha1)

    def test_import_tree_with_file(self):
        inv = Inventory()
        inv.revision_id = "somerevid"
        blob = Blob.from_string("bar1")
        tree = Tree()
        tree.add(0100600, "foo", blob.id)
        tree.serialize()
        objects = { blob.id: blob, tree.id: tree }
        import_git_tree(self._texts, self._mapping, "bla", tree, inv, [], 
            self._map, objects.__getitem__)
        self.assertEquals(["foo"], inv["bla"].children.keys())
        self.assertEquals(set(["bla", "bla/foo"]), 
                set([ie.file_id for (path, ie) in inv.entries()]))
        ie = inv["bla/foo"]
        self.assertEquals("file", ie.kind)
        self.assertEquals("bla/foo", ie.file_id)
        self.assertEquals("somerevid", ie.revision)
        self.assertEquals(osutils.sha_strings(["bar1"]), ie.text_sha1)
        self.assertEquals(False, ie.executable)

    def test_import_tree_with_file_exe(self):
        inv = Inventory()
        inv.revision_id = "somerevid"
        blob = Blob.from_string("bar")
        tree = Tree()
        tree.add(0100755, "foo", blob.id)
        tree.serialize()
        objects = { blob.id: blob, tree.id: tree }
        import_git_tree(self._texts, self._mapping, "bla", tree, inv, [], 
            self._map, objects.__getitem__)
        self.assertEquals(["foo"], inv["bla"].children.keys())
        ie = inv["bla/foo"]
        self.assertEquals("file", ie.kind)
        self.assertEquals(True, ie.executable)

