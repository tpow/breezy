# Copyright (C) 2010 Jelmer Vernooij <jelmer@samba.org>
# -*- encoding: utf-8 -*-
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


"""Tests for roundtripping text parsing."""


from bzrlib.tests import TestCase

from bzrlib.plugins.git.roundtrip import (
    BzrGitRevisionMetadata,
    extract_bzr_metadata,
    generate_roundtripping_metadata,
    inject_bzr_metadata,
    parse_roundtripping_metadata,
    )


class RoundtripTests(TestCase):

    def test_revid(self):
        md = parse_roundtripping_metadata("revision-id: foo\n")
        self.assertEquals("foo", md.revision_id)


class FormatTests(TestCase):

    def test_simple(self):
        metadata = BzrGitRevisionMetadata()
        metadata.revision_id = "bla"
        self.assertEquals("revision-id: bla\n",
            generate_roundtripping_metadata(metadata))


class ExtractMetadataTests(TestCase):

    def test_roundtrip(self):
        (msg, metadata) = extract_bzr_metadata("""Foo
--BZR--
revision-id: foo
""")
        self.assertEquals("Foo", msg)
        self.assertEquals("foo", metadata.revision_id)


class GenerateMetadataTests(TestCase):

    def test_roundtrip(self):
        metadata = BzrGitRevisionMetadata()
        metadata.revision_id = "myrevid"
        msg = inject_bzr_metadata("Foo", metadata)
        self.assertEquals("""Foo
--BZR--
revision-id: myrevid
""", msg)
