# Copyright (C) 2007 Canonical Ltd
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

"""Benchmarks for Knit performance"""

import os

from bzrlib import (
    generate_ids,
    knit,
    tests,
    )
from bzrlib.benchmarks import Benchmark
from bzrlib.tests.test_knit import CompiledKnitFeature


class BenchKnitIndex(Benchmark):
    """Benchmark Knit index performance."""

    def create_10k_index(self):
        """Create an knit index file with 10,000 entries.

        This isn't super realistic, but it *is* big :)

        The file 'test.kndx' will be created.
        """
        rev_id = generate_ids.gen_revision_id('long.name@this.example.com')
        versions = [(rev_id, ('fulltext',), 0, 200, [])]
        pos = 200
        for i in xrange(9999):
            parent_ids = [rev_id]
            rev_id = generate_ids.gen_revision_id('long.name@this.example.com')
            versions.append((rev_id, ('line-delta',), pos, 200, parent_ids))
            pos += 200
        t = self.get_transport()
        kndx = knit._KnitIndex(t, 'test.kndx', 'w', create=True,
                               delay_create=True)
        kndx.add_versions(versions)

    def setup_load_data_c(self):
        self.requireFeature(CompiledKnitFeature)
        orig = knit._load_data
        def reset():
            knit._load_data = orig
        self.addCleanup(reset)
        knit._load_data = knit._load_data_c

    def setup_load_data_py(self):
        orig = knit._load_data
        def reset():
            knit._load_data = orig
        self.addCleanup(reset)
        knit._load_data = knit._load_data_py

    def test_read_10k_index_c(self):
        self.create_10k_index()
        self.setup_load_data_c()
        t = self.get_transport()
        kndx = self.time(knit._KnitIndex, t, 'test.kndx', 'r')

    def test_read_10k_index_c_again(self):
        self.create_10k_index()
        self.setup_load_data_c()
        t = self.get_transport()
        kndx = self.time(knit._KnitIndex, t, 'test.kndx', 'r')

    def test_read_10k_index_py(self):
        self.create_10k_index()
        self.setup_load_data_py()
        t = self.get_transport()
        kndx = self.time(knit._KnitIndex, t, 'test.kndx', 'r')

    def test_read_10k_index_py_again(self):
        self.create_10k_index()
        self.setup_load_data_py()
        t = self.get_transport()
        kndx = self.time(knit._KnitIndex, t, 'test.kndx', 'r')
