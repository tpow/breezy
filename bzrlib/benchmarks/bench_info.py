# Copyright (C) 2006 Canonical Ltd
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

"""Tests for bzr info performance."""


from bzrlib.benchmarks import Benchmark


class InfoBenchmark(Benchmark):
    """This is a stub. Use this benchmark with a network transport.
    Currently "bzr info sftp://..." takes > 4 min"""

    def test_no_ignored_unknown_kernel_like_tree(self):
        """Info in a kernel sized tree with no ignored or unknowns. """
        self.make_kernel_like_added_tree()
        self.time(self.run_bzr, 'info')

    def test_no_changes_known_kernel_like_tree(self):
        """Info in a kernel sized tree with no ignored, unknowns, or added."""
        self.make_kernel_like_committed_tree()
        self.time(self.run_bzr, 'info')


