# Copyright (C) 2010 Jelmer Vernooij
# Copyright (C) 2011 Canonical Ltd.
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

"""Tests for Git working trees."""

from bzrlib import (
    conflicts as _mod_conflicts,
    )
from bzrlib.tests import TestCaseWithTransport


class GitWorkingTreeTests(TestCaseWithTransport):

    def setUp(self):
        super(GitWorkingTreeTests, self).setUp()
        self.tree = self.make_branch_and_tree('.', format="git")

    def test_conflicts(self):
        self.assertIsInstance(self.tree.conflicts(),
            _mod_conflicts.ConflictList)