# Copyright (C) 2005-2010 Aaron Bentley, Canonical Ltd
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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA


import os.path

from breezy.tests import TestCase

from breezy.iterablefile import IterableFile
from breezy.patches import (MalformedLine,
                            MalformedHunkHeader,
                            MalformedPatchHeader,
                            BinaryPatch,
                            BinaryFiles,
                            Patch,
                            ContextLine,
                            InsertLine,
                            RemoveLine,
                            difference_index,
                            get_patch_names,
                            hunk_from_header,
                            iter_patched,
                            iter_patched_from_hunks,
                            parse_line,
                            parse_patch,
                            parse_patches,
                            NO_NL)


class PatchesTester(TestCase):

    def datafile(self, filename):
        data_path = os.path.join(os.path.dirname(__file__),
                                 "test_patches_data", filename)
        return file(data_path, "rb")

    def data_lines(self, filename):
        datafile = self.datafile(filename)
        try:
            return datafile.readlines()
        finally:
            datafile.close()

    def test_parse_patches_leading_noise(self):
        # https://bugs.launchpad.net/bzr/+bug/502076
        # https://code.launchpad.net/~toshio/bzr/allow-dirty-patches/+merge/18854
        lines = ["diff -pruN commands.py",
                 "--- orig/commands.py",
                 "+++ mod/dommands.py"]
        bits = parse_patches(iter(lines), allow_dirty=True)

    def test_preserve_dirty_head(self):
        """Parse a patch containing a dirty header, and preserve lines"""
        lines = ["=== added directory 'foo/bar'\n",
                 "=== modified file 'orig/commands.py'\n",
                 "--- orig/commands.py\n",
                 "+++ mod/dommands.py\n",
                 "=== modified file 'orig/another.py'\n",
                 "--- orig/another.py\n",
                 "+++ mod/another.py\n"]
        patches = parse_patches(
            lines.__iter__(), allow_dirty=True, keep_dirty=True)
        self.assertLength(2, patches)
        self.assertEqual(patches[0]['dirty_head'],
                         ["=== added directory 'foo/bar'\n",
                          "=== modified file 'orig/commands.py'\n"])
        self.assertEqual(patches[0]['patch'].get_header().splitlines(True),
                         ["--- orig/commands.py\n", "+++ mod/dommands.py\n"])
        self.assertEqual(patches[1]['dirty_head'],
                         ["=== modified file 'orig/another.py'\n"])
        self.assertEqual(patches[1]['patch'].get_header().splitlines(True),
                         ["--- orig/another.py\n", "+++ mod/another.py\n"])

    def testValidPatchHeader(self):
        """Parse a valid patch header"""
        lines = "--- orig/commands.py\n+++ mod/dommands.py\n".split('\n')
        (orig, mod) = get_patch_names(lines.__iter__())
        self.assertEqual(orig, "orig/commands.py")
        self.assertEqual(mod, "mod/dommands.py")

    def testInvalidPatchHeader(self):
        """Parse an invalid patch header"""
        lines = "-- orig/commands.py\n+++ mod/dommands.py".split('\n')
        self.assertRaises(MalformedPatchHeader, get_patch_names,
                          lines.__iter__())

    def testValidHunkHeader(self):
        """Parse a valid hunk header"""
        header = "@@ -34,11 +50,6 @@\n"
        hunk = hunk_from_header(header)
        self.assertEqual(hunk.orig_pos, 34)
        self.assertEqual(hunk.orig_range, 11)
        self.assertEqual(hunk.mod_pos, 50)
        self.assertEqual(hunk.mod_range, 6)
        self.assertEqual(str(hunk), header)

    def testValidHunkHeader2(self):
        """Parse a tricky, valid hunk header"""
        header = "@@ -1 +0,0 @@\n"
        hunk = hunk_from_header(header)
        self.assertEqual(hunk.orig_pos, 1)
        self.assertEqual(hunk.orig_range, 1)
        self.assertEqual(hunk.mod_pos, 0)
        self.assertEqual(hunk.mod_range, 0)
        self.assertEqual(str(hunk), header)

    def testPDiff(self):
        """Parse a hunk header produced by diff -p"""
        header = "@@ -407,7 +292,7 @@ bzr 0.18rc1  2007-07-10\n"
        hunk = hunk_from_header(header)
        self.assertEqual('bzr 0.18rc1  2007-07-10', hunk.tail)
        self.assertEqual(header, str(hunk))

    def makeMalformed(self, header):
        self.assertRaises(MalformedHunkHeader, hunk_from_header, header)

    def testInvalidHeader(self):
        """Parse an invalid hunk header"""
        self.makeMalformed(" -34,11 +50,6 \n")
        self.makeMalformed("@@ +50,6 -34,11 @@\n")
        self.makeMalformed("@@ -34,11 +50,6 @@")
        self.makeMalformed("@@ -34.5,11 +50,6 @@\n")
        self.makeMalformed("@@-34,11 +50,6@@\n")
        self.makeMalformed("@@ 34,11 50,6 @@\n")
        self.makeMalformed("@@ -34,11 @@\n")
        self.makeMalformed("@@ -34,11 +50,6.5 @@\n")
        self.makeMalformed("@@ -34,11 +50,-6 @@\n")

    def lineThing(self, text, type):
        line = parse_line(text)
        self.assertIsInstance(line, type)
        self.assertEqual(str(line), text)

    def makeMalformedLine(self, text):
        self.assertRaises(MalformedLine, parse_line, text)

    def testValidLine(self):
        """Parse a valid hunk line"""
        self.lineThing(" hello\n", ContextLine)
        self.lineThing("+hello\n", InsertLine)
        self.lineThing("-hello\n", RemoveLine)

    def testMalformedLine(self):
        """Parse invalid valid hunk lines"""
        self.makeMalformedLine("hello\n")

    def testMalformedLineNO_NL(self):
        """Parse invalid '\ No newline at end of file' in hunk lines"""
        self.makeMalformedLine(NO_NL)

    def compare_parsed(self, patchtext):
        lines = patchtext.splitlines(True)
        patch = parse_patch(lines.__iter__())
        pstr = str(patch)
        i = difference_index(patchtext, pstr)
        if i is not None:
            print("%i: \"%s\" != \"%s\"" % (i, patchtext[i], pstr[i]))
        self.assertEqual(patchtext, str(patch))

    def testAll(self):
        """Test parsing a whole patch"""
        patchtext = self.datafile("patchtext.patch").read()
        self.compare_parsed(patchtext)

    def test_parse_binary(self):
        """Test parsing a whole patch"""
        patches = parse_patches(self.data_lines("binary.patch"))
        self.assertIs(BinaryPatch, patches[0].__class__)
        self.assertIs(Patch, patches[1].__class__)
        self.assertContainsRe(patches[0].oldname, '^bar\t')
        self.assertContainsRe(patches[0].newname, '^qux\t')
        self.assertContainsRe(str(patches[0]),
                              'Binary files bar\t.* and qux\t.* differ\n')

    def test_parse_binary_after_normal(self):
        patches = parse_patches(self.data_lines("binary-after-normal.patch"))
        self.assertIs(BinaryPatch, patches[1].__class__)
        self.assertIs(Patch, patches[0].__class__)
        self.assertContainsRe(patches[1].oldname, '^bar\t')
        self.assertContainsRe(patches[1].newname, '^qux\t')
        self.assertContainsRe(str(patches[1]),
                              'Binary files bar\t.* and qux\t.* differ\n')

    def test_roundtrip_binary(self):
        patchtext = ''.join(self.data_lines("binary.patch"))
        patches = parse_patches(patchtext.splitlines(True))
        self.assertEqual(patchtext, ''.join(str(p) for p in patches))

    def testInit(self):
        """Handle patches missing half the position, range tuple"""
        patchtext = \
"""--- orig/__vavg__.cl
+++ mod/__vavg__.cl
@@ -1 +1,2 @@
 __qbpsbezng__ = "erfgehpgherqgrkg ra"
+__qbp__ = Na nygreangr Nepu pbzznaqyvar vagresnpr
"""
        self.compare_parsed(patchtext)

    def testLineLookup(self):
        import sys
        """Make sure we can accurately look up mod line from orig"""
        patch = parse_patch(self.datafile("diff"))
        orig = list(self.datafile("orig"))
        mod = list(self.datafile("mod"))
        removals = []
        for i in range(len(orig)):
            mod_pos = patch.pos_in_mod(i)
            if mod_pos is None:
                removals.append(orig[i])
                continue
            self.assertEqual(mod[mod_pos], orig[i])
        rem_iter = removals.__iter__()
        for hunk in patch.hunks:
            for line in hunk.lines:
                if isinstance(line, RemoveLine):
                    next = rem_iter.next()
                    if line.contents != next:
                        sys.stdout.write(" orig:%spatch:%s" % (next,
                                         line.contents))
                    self.assertEqual(line.contents, next)
        self.assertRaises(StopIteration, rem_iter.next)

    def testPatching(self):
        """Test a few patch files, and make sure they work."""
        files = [
            ('diff-2', 'orig-2', 'mod-2'),
            ('diff-3', 'orig-3', 'mod-3'),
            ('diff-4', 'orig-4', 'mod-4'),
            ('diff-5', 'orig-5', 'mod-5'),
            ('diff-6', 'orig-6', 'mod-6'),
            ('diff-7', 'orig-7', 'mod-7'),
        ]
        for diff, orig, mod in files:
            patch = self.datafile(diff)
            orig_lines = list(self.datafile(orig))
            mod_lines = list(self.datafile(mod))

            patched_file = IterableFile(iter_patched(orig_lines, patch))
            count = 0
            for patch_line in patched_file:
                self.assertEqual(patch_line, mod_lines[count])
                count += 1
            self.assertEqual(count, len(mod_lines))

    def test_iter_patched_binary(self):
        binary_lines = self.data_lines('binary.patch')
        e = self.assertRaises(BinaryFiles, iter_patched, [], binary_lines)

    def test_iter_patched_from_hunks(self):
        """Test a few patch files, and make sure they work."""
        files = [
            ('diff-2', 'orig-2', 'mod-2'),
            ('diff-3', 'orig-3', 'mod-3'),
            ('diff-4', 'orig-4', 'mod-4'),
            ('diff-5', 'orig-5', 'mod-5'),
            ('diff-6', 'orig-6', 'mod-6'),
            ('diff-7', 'orig-7', 'mod-7'),
        ]
        for diff, orig, mod in files:
            parsed = parse_patch(self.datafile(diff))
            orig_lines = list(self.datafile(orig))
            mod_lines = list(self.datafile(mod))
            iter_patched = iter_patched_from_hunks(orig_lines, parsed.hunks)
            patched_file = IterableFile(iter_patched)
            count = 0
            for patch_line in patched_file:
                self.assertEqual(patch_line, mod_lines[count])
                count += 1
            self.assertEqual(count, len(mod_lines))

    def testFirstLineRenumber(self):
        """Make sure we handle lines at the beginning of the hunk"""
        patch = parse_patch(self.datafile("insert_top.patch"))
        self.assertEqual(patch.pos_in_mod(0), 1)

    def testParsePatches(self):
        """Make sure file names can be extracted from tricky unified diffs"""
        patchtext = \
"""--- orig-7
+++ mod-7
@@ -1,10 +1,10 @@
 -- a
--- b
+++ c
 xx d
 xx e
 ++ f
-++ g
+-- h
 xx i
 xx j
 -- k
--- l
+++ m
--- orig-8
+++ mod-8
@@ -1 +1 @@
--- A
+++ B
@@ -1 +1 @@
--- C
+++ D
"""
        filenames = [('orig-7', 'mod-7'),
                     ('orig-8', 'mod-8')]
        patches = parse_patches(patchtext.splitlines(True))
        patch_files = []
        for patch in patches:
            patch_files.append((patch.oldname, patch.newname))
        self.assertEqual(patch_files, filenames)

    def testStatsValues(self):
        """Test the added, removed and hunks values for stats_values."""
        patch = parse_patch(self.datafile("diff"))
        self.assertEqual((299, 407, 48), patch.stats_values())
