# Copyright (C) 2009 Canonical Ltd
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

"""Tests for the python and pyrex extensions of KnownGraph"""

import pprint

from bzrlib import (
    errors,
    graph as _mod_graph,
    _known_graph_py,
    tests,
    )
from bzrlib.tests import test_graph
from bzrlib.revision import NULL_REVISION


def load_tests(standard_tests, module, loader):
    """Parameterize tests for all versions of groupcompress."""
    scenarios = [
        ('python', {'module': _known_graph_py, 'do_cache': True}),
    ]
    caching_scenarios = [
        ('python-nocache', {'module': _known_graph_py, 'do_cache': False}),
    ]
    suite = loader.suiteClass()
    if compiled_known_graph_feature.available():
        scenarios.append(('C', {'module': compiled_known_graph_feature.module,
                                'do_cache': True}))
        caching_scenarios.append(
            ('C-nocache', {'module': compiled_known_graph_feature.module,
                           'do_cache': False}))
    else:
        # the compiled module isn't available, so we add a failing test
        class FailWithoutFeature(tests.TestCase):
            def test_fail(self):
                self.requireFeature(compiled_known_graph_feature)
        suite.addTest(loader.loadTestsFromTestCase(FailWithoutFeature))
    # TestKnownGraphHeads needs to be permutated with and without caching.
    # All other TestKnownGraph tests only need to be tested across module
    heads_suite, other_suite = tests.split_suite_by_condition(
        standard_tests, tests.condition_isinstance(TestKnownGraphHeads))
    suite = tests.multiply_tests(other_suite, scenarios, suite)
    suite = tests.multiply_tests(heads_suite, scenarios + caching_scenarios,
                                 suite)
    return suite


compiled_known_graph_feature = tests.ModuleAvailableFeature(
                                    'bzrlib._known_graph_pyx')


#  a
#  |\
#  b |
#  | |
#  c |
#   \|
#    d
alt_merge = {'a': [], 'b': ['a'], 'c': ['b'], 'd': ['a', 'c']}


class TestCaseWithKnownGraph(tests.TestCase):

    module = None # Set by load_tests

    def make_known_graph(self, ancestry):
        return self.module.KnownGraph(ancestry, do_cache=self.do_cache)


class TestKnownGraph(TestCaseWithKnownGraph):

    def assertGDFO(self, graph, rev, gdfo):
        node = graph._nodes[rev]
        self.assertEqual(gdfo, node.gdfo)

    def test_children_ancestry1(self):
        graph = self.make_known_graph(test_graph.ancestry_1)
        self.assertEqual(['rev1'], graph.get_child_keys(NULL_REVISION))
        self.assertEqual(['rev2a', 'rev2b'],
                         sorted(graph.get_child_keys('rev1')))
        self.assertEqual(['rev3'], graph.get_child_keys('rev2a'))
        self.assertEqual(['rev4'], graph.get_child_keys('rev3'))
        self.assertEqual(['rev4'], graph.get_child_keys('rev2b'))
        self.assertRaises(KeyError, graph.get_child_keys, 'not_in_graph')

    def test_parent_ancestry1(self):
        graph = self.make_known_graph(test_graph.ancestry_1)
        self.assertEqual([NULL_REVISION], graph.get_parent_keys('rev1'))
        self.assertEqual(['rev1'], graph.get_parent_keys('rev2a'))
        self.assertEqual(['rev1'], graph.get_parent_keys('rev2b'))
        self.assertEqual(['rev2a'], graph.get_parent_keys('rev3'))
        self.assertEqual(['rev2b', 'rev3'],
                         sorted(graph.get_parent_keys('rev4')))
        self.assertRaises(KeyError, graph.get_child_keys, 'not_in_graph')
    
    def test_parent_with_ghost(self):
        graph = self.make_known_graph(test_graph.with_ghost)
        self.assertEqual(None, graph.get_parent_keys('g'))

    def test_gdfo_ancestry_1(self):
        graph = self.make_known_graph(test_graph.ancestry_1)
        self.assertGDFO(graph, 'rev1', 2)
        self.assertGDFO(graph, 'rev2b', 3)
        self.assertGDFO(graph, 'rev2a', 3)
        self.assertGDFO(graph, 'rev3', 4)
        self.assertGDFO(graph, 'rev4', 5)

    def test_gdfo_feature_branch(self):
        graph = self.make_known_graph(test_graph.feature_branch)
        self.assertGDFO(graph, 'rev1', 2)
        self.assertGDFO(graph, 'rev2b', 3)
        self.assertGDFO(graph, 'rev3b', 4)

    def test_gdfo_extended_history_shortcut(self):
        graph = self.make_known_graph(test_graph.extended_history_shortcut)
        self.assertGDFO(graph, 'a', 2)
        self.assertGDFO(graph, 'b', 3)
        self.assertGDFO(graph, 'c', 4)
        self.assertGDFO(graph, 'd', 5)
        self.assertGDFO(graph, 'e', 6)
        self.assertGDFO(graph, 'f', 6)

    def test_gdfo_with_ghost(self):
        graph = self.make_known_graph(test_graph.with_ghost)
        self.assertGDFO(graph, 'f', 2)
        self.assertGDFO(graph, 'e', 3)
        self.assertGDFO(graph, 'g', 1)
        self.assertGDFO(graph, 'b', 4)
        self.assertGDFO(graph, 'd', 4)
        self.assertGDFO(graph, 'a', 5)
        self.assertGDFO(graph, 'c', 5)

    def test_add_existing_node(self):
        graph = self.make_known_graph(test_graph.ancestry_1)
        # Add a node that already exists with identical content
        # This is a 'no-op'
        self.assertGDFO(graph, 'rev4', 5)
        graph.add_node('rev4', ['rev3', 'rev2b'])
        self.assertGDFO(graph, 'rev4', 5)
        # This also works if we use a tuple rather than a list
        graph.add_node('rev4', ('rev3', 'rev2b'))

    def test_add_existing_node_mismatched_parents(self):
        graph = self.make_known_graph(test_graph.ancestry_1)
        self.assertRaises(ValueError, graph.add_node, 'rev4',
                          ['rev2b', 'rev3'])

    def test_add_node_with_ghost_parent(self):
        graph = self.make_known_graph(test_graph.ancestry_1)
        graph.add_node('rev5', ['rev2b', 'revGhost'])
        self.assertGDFO(graph, 'rev5', 4)
        self.assertGDFO(graph, 'revGhost', 1)

    def test_add_new_root(self):
        graph = self.make_known_graph(test_graph.ancestry_1)
        graph.add_node('rev5', [])
        self.assertGDFO(graph, 'rev5', 1)

    def test_add_with_all_ghost_parents(self):
        graph = self.make_known_graph(test_graph.ancestry_1)
        graph.add_node('rev5', ['ghost'])
        self.assertGDFO(graph, 'rev5', 2)
        self.assertGDFO(graph, 'ghost', 1)

    def test_gdfo_after_add_node(self):
        graph = self.make_known_graph(test_graph.ancestry_1)
        self.assertEqual([], graph.get_child_keys('rev4'))
        graph.add_node('rev5', ['rev4'])
        self.assertEqual(['rev4'], graph.get_parent_keys('rev5'))
        self.assertEqual(['rev5'], graph.get_child_keys('rev4'))
        self.assertEqual([], graph.get_child_keys('rev5'))
        self.assertGDFO(graph, 'rev5', 6)
        graph.add_node('rev6', ['rev2b'])
        graph.add_node('rev7', ['rev6'])
        graph.add_node('rev8', ['rev7', 'rev5'])
        self.assertGDFO(graph, 'rev5', 6)
        self.assertGDFO(graph, 'rev6', 4)
        self.assertGDFO(graph, 'rev7', 5)
        self.assertGDFO(graph, 'rev8', 7)

    def test_fill_in_ghost(self):
        graph = self.make_known_graph(test_graph.with_ghost)
        # Add in a couple nodes and then fill in the 'ghost' so that it should
        # cause renumbering of children nodes
        graph.add_node('x', [])
        graph.add_node('y', ['x'])
        graph.add_node('z', ['y'])
        graph.add_node('g', ['z'])
        self.assertGDFO(graph, 'f', 2)
        self.assertGDFO(graph, 'e', 3)
        self.assertGDFO(graph, 'x', 1)
        self.assertGDFO(graph, 'y', 2)
        self.assertGDFO(graph, 'z', 3)
        self.assertGDFO(graph, 'g', 4)
        self.assertGDFO(graph, 'b', 4)
        self.assertGDFO(graph, 'd', 5)
        self.assertGDFO(graph, 'a', 5)
        self.assertGDFO(graph, 'c', 6)


class TestKnownGraphHeads(TestCaseWithKnownGraph):

    do_cache = None # Set by load_tests

    def test_heads_null(self):
        graph = self.make_known_graph(test_graph.ancestry_1)
        self.assertEqual(set(['null:']), graph.heads(['null:']))
        self.assertEqual(set(['rev1']), graph.heads(['null:', 'rev1']))
        self.assertEqual(set(['rev1']), graph.heads(['rev1', 'null:']))
        self.assertEqual(set(['rev1']), graph.heads(set(['rev1', 'null:'])))
        self.assertEqual(set(['rev1']), graph.heads(('rev1', 'null:')))

    def test_heads_one(self):
        # A single node will always be a head
        graph = self.make_known_graph(test_graph.ancestry_1)
        self.assertEqual(set(['null:']), graph.heads(['null:']))
        self.assertEqual(set(['rev1']), graph.heads(['rev1']))
        self.assertEqual(set(['rev2a']), graph.heads(['rev2a']))
        self.assertEqual(set(['rev2b']), graph.heads(['rev2b']))
        self.assertEqual(set(['rev3']), graph.heads(['rev3']))
        self.assertEqual(set(['rev4']), graph.heads(['rev4']))

    def test_heads_single(self):
        graph = self.make_known_graph(test_graph.ancestry_1)
        self.assertEqual(set(['rev4']), graph.heads(['null:', 'rev4']))
        self.assertEqual(set(['rev2a']), graph.heads(['rev1', 'rev2a']))
        self.assertEqual(set(['rev2b']), graph.heads(['rev1', 'rev2b']))
        self.assertEqual(set(['rev3']), graph.heads(['rev1', 'rev3']))
        self.assertEqual(set(['rev3']), graph.heads(['rev3', 'rev2a']))
        self.assertEqual(set(['rev4']), graph.heads(['rev1', 'rev4']))
        self.assertEqual(set(['rev4']), graph.heads(['rev2a', 'rev4']))
        self.assertEqual(set(['rev4']), graph.heads(['rev2b', 'rev4']))
        self.assertEqual(set(['rev4']), graph.heads(['rev3', 'rev4']))

    def test_heads_two_heads(self):
        graph = self.make_known_graph(test_graph.ancestry_1)
        self.assertEqual(set(['rev2a', 'rev2b']),
                         graph.heads(['rev2a', 'rev2b']))
        self.assertEqual(set(['rev3', 'rev2b']),
                         graph.heads(['rev3', 'rev2b']))

    def test_heads_criss_cross(self):
        graph = self.make_known_graph(test_graph.criss_cross)
        self.assertEqual(set(['rev2a']),
                         graph.heads(['rev2a', 'rev1']))
        self.assertEqual(set(['rev2b']),
                         graph.heads(['rev2b', 'rev1']))
        self.assertEqual(set(['rev3a']),
                         graph.heads(['rev3a', 'rev1']))
        self.assertEqual(set(['rev3b']),
                         graph.heads(['rev3b', 'rev1']))
        self.assertEqual(set(['rev2a', 'rev2b']),
                         graph.heads(['rev2a', 'rev2b']))
        self.assertEqual(set(['rev3a']),
                         graph.heads(['rev3a', 'rev2a']))
        self.assertEqual(set(['rev3a']),
                         graph.heads(['rev3a', 'rev2b']))
        self.assertEqual(set(['rev3a']),
                         graph.heads(['rev3a', 'rev2a', 'rev2b']))
        self.assertEqual(set(['rev3b']),
                         graph.heads(['rev3b', 'rev2a']))
        self.assertEqual(set(['rev3b']),
                         graph.heads(['rev3b', 'rev2b']))
        self.assertEqual(set(['rev3b']),
                         graph.heads(['rev3b', 'rev2a', 'rev2b']))
        self.assertEqual(set(['rev3a', 'rev3b']),
                         graph.heads(['rev3a', 'rev3b']))
        self.assertEqual(set(['rev3a', 'rev3b']),
                         graph.heads(['rev3a', 'rev3b', 'rev2a', 'rev2b']))

    def test_heads_shortcut(self):
        graph = self.make_known_graph(test_graph.history_shortcut)
        self.assertEqual(set(['rev2a', 'rev2b', 'rev2c']),
                         graph.heads(['rev2a', 'rev2b', 'rev2c']))
        self.assertEqual(set(['rev3a', 'rev3b']),
                         graph.heads(['rev3a', 'rev3b']))
        self.assertEqual(set(['rev3a', 'rev3b']),
                         graph.heads(['rev2a', 'rev3a', 'rev3b']))
        self.assertEqual(set(['rev2a', 'rev3b']),
                         graph.heads(['rev2a', 'rev3b']))
        self.assertEqual(set(['rev2c', 'rev3a']),
                         graph.heads(['rev2c', 'rev3a']))

    def test_heads_linear(self):
        graph = self.make_known_graph(test_graph.racing_shortcuts)
        self.assertEqual(set(['w']), graph.heads(['w', 's']))
        self.assertEqual(set(['z']), graph.heads(['w', 's', 'z']))
        self.assertEqual(set(['w', 'q']), graph.heads(['w', 's', 'q']))
        self.assertEqual(set(['z']), graph.heads(['s', 'z']))

    def test_heads_alt_merge(self):
        graph = self.make_known_graph(alt_merge)
        self.assertEqual(set(['c']), graph.heads(['a', 'c']))

    def test_heads_with_ghost(self):
        graph = self.make_known_graph(test_graph.with_ghost)
        self.assertEqual(set(['e', 'g']), graph.heads(['e', 'g']))
        self.assertEqual(set(['a', 'c']), graph.heads(['a', 'c']))
        self.assertEqual(set(['a', 'g']), graph.heads(['a', 'g']))
        self.assertEqual(set(['f', 'g']), graph.heads(['f', 'g']))
        self.assertEqual(set(['c']), graph.heads(['c', 'g']))
        self.assertEqual(set(['c']), graph.heads(['c', 'b', 'd', 'g']))
        self.assertEqual(set(['a', 'c']), graph.heads(['a', 'c', 'e', 'g']))
        self.assertEqual(set(['a', 'c']), graph.heads(['a', 'c', 'f']))

    def test_filling_in_ghosts_resets_head_cache(self):
        graph = self.make_known_graph(test_graph.with_ghost)
        self.assertEqual(set(['e', 'g']), graph.heads(['e', 'g']))
        # 'g' is filled in, and decends from 'e', so the heads result is now
        # different
        graph.add_node('g', ['e'])
        self.assertEqual(set(['g']), graph.heads(['e', 'g']))


class TestKnownGraphTopoSort(TestCaseWithKnownGraph):

    def assertTopoSortOrder(self, ancestry):
        """Check topo_sort and iter_topo_order is genuinely topological order.

        For every child in the graph, check if it comes after all of it's
        parents.
        """
        graph = self.make_known_graph(ancestry)
        sort_result = graph.topo_sort()
        # We should have an entry in sort_result for every entry present in the
        # graph.
        self.assertEqual(len(ancestry), len(sort_result))
        node_idx = dict((node, idx) for idx, node in enumerate(sort_result))
        for node in sort_result:
            parents = ancestry[node]
            for parent in parents:
                if parent not in ancestry:
                    # ghost
                    continue
                if node_idx[node] <= node_idx[parent]:
                    self.fail("parent %s must come before child %s:\n%s"
                              % (parent, node, sort_result))

    def test_topo_sort_empty(self):
        """TopoSort empty list"""
        self.assertTopoSortOrder({})

    def test_topo_sort_easy(self):
        """TopoSort list with one node"""
        self.assertTopoSortOrder({0: []})

    def test_topo_sort_cycle(self):
        """TopoSort traps graph with cycles"""
        g = self.make_known_graph({0: [1],
                                  1: [0]})
        self.assertRaises(errors.GraphCycleError, g.topo_sort)

    def test_topo_sort_cycle_2(self):
        """TopoSort traps graph with longer cycle"""
        g = self.make_known_graph({0: [1],
                                   1: [2],
                                   2: [0]})
        self.assertRaises(errors.GraphCycleError, g.topo_sort)

    def test_topo_sort_cycle_with_tail(self):
        """TopoSort traps graph with longer cycle"""
        g = self.make_known_graph({0: [1],
                                   1: [2],
                                   2: [3, 4],
                                   3: [0],
                                   4: []})
        self.assertRaises(errors.GraphCycleError, g.topo_sort)

    def test_topo_sort_1(self):
        """TopoSort simple nontrivial graph"""
        self.assertTopoSortOrder({0: [3],
                                  1: [4],
                                  2: [1, 4],
                                  3: [],
                                  4: [0, 3]})

    def test_topo_sort_partial(self):
        """Topological sort with partial ordering.

        Multiple correct orderings are possible, so test for
        correctness, not for exact match on the resulting list.
        """
        self.assertTopoSortOrder({0: [],
                                  1: [0],
                                  2: [0],
                                  3: [0],
                                  4: [1, 2, 3],
                                  5: [1, 2],
                                  6: [1, 2],
                                  7: [2, 3],
                                  8: [0, 1, 4, 5, 6]})

    def test_topo_sort_ghost_parent(self):
        """Sort nodes, but don't include some parents in the output"""
        self.assertTopoSortOrder({0: [1],
                                  1: [2]})


class TestKnownGraphMergeSort(TestCaseWithKnownGraph):

    def assertSortAndIterate(self, ancestry, branch_tip, result_list):
        """Check that merge based sorting and iter_topo_order on graph works."""
        graph = self.make_known_graph(ancestry)
        value = graph.merge_sort(branch_tip)
        value = [(n.key, n.merge_depth, n.revno, n.end_of_merge)
                 for n in value]
        if result_list != value:
            self.assertEqualDiff(pprint.pformat(result_list),
                                 pprint.pformat(value))

    def test_merge_sort_empty(self):
        # sorting of an emptygraph does not error
        self.assertSortAndIterate({}, None, [])
        self.assertSortAndIterate({}, NULL_REVISION, [])
        self.assertSortAndIterate({}, (NULL_REVISION,), [])

    def test_merge_sort_not_empty_no_tip(self):
        # merge sorting of a branch starting with None should result
        # in an empty list: no revisions are dragged in.
        self.assertSortAndIterate({0: []}, None, [])
        self.assertSortAndIterate({0: []}, NULL_REVISION, [])
        self.assertSortAndIterate({0: []}, (NULL_REVISION,), [])

    def test_merge_sort_one_revision(self):
        # sorting with one revision as the tip returns the correct fields:
        # sequence - 0, revision id, merge depth - 0, end_of_merge
        self.assertSortAndIterate({'id': []},
                                  'id',
                                  [('id', 0, (1,), True)])

    def test_sequence_numbers_increase_no_merges(self):
        # emit a few revisions with no merges to check the sequence
        # numbering works in trivial cases
        self.assertSortAndIterate(
            {'A': [],
             'B': ['A'],
             'C': ['B']},
            'C',
            [('C', 0, (3,), False),
             ('B', 0, (2,), False),
             ('A', 0, (1,), True),
             ],
            )

    def test_sequence_numbers_increase_with_merges(self):
        # test that sequence numbers increase across merges
        self.assertSortAndIterate(
            {'A': [],
             'B': ['A'],
             'C': ['A', 'B']},
            'C',
            [('C', 0, (2,), False),
             ('B', 1, (1,1,1), True),
             ('A', 0, (1,), True),
             ],
            )

    def test_merge_sort_race(self):
        # A
        # |
        # B-.
        # |\ \
        # | | C
        # | |/
        # | D
        # |/
        # F
        graph = {'A': [],
                 'B': ['A'],
                 'C': ['B'],
                 'D': ['B', 'C'],
                 'F': ['B', 'D'],
                 }
        self.assertSortAndIterate(graph, 'F',
            [('F', 0, (3,), False),
             ('D', 1, (2,2,1), False),
             ('C', 2, (2,1,1), True),
             ('B', 0, (2,), False),
             ('A', 0, (1,), True),
             ])
        # A
        # |
        # B-.
        # |\ \
        # | X C
        # | |/
        # | D
        # |/
        # F
        graph = {'A': [],
                 'B': ['A'],
                 'C': ['B'],
                 'X': ['B'],
                 'D': ['X', 'C'],
                 'F': ['B', 'D'],
                 }
        self.assertSortAndIterate(graph, 'F',
            [('F', 0, (3,), False),
             ('D', 1, (2,1,2), False),
             ('C', 2, (2,2,1), True),
             ('X', 1, (2,1,1), True),
             ('B', 0, (2,), False),
             ('A', 0, (1,), True),
             ])

    def test_merge_depth_with_nested_merges(self):
        # the merge depth marker should reflect the depth of the revision
        # in terms of merges out from the mainline
        # revid, depth, parents:
        #  A 0   [D, B]
        #  B  1  [C, F]
        #  C  1  [H]
        #  D 0   [H, E]
        #  E  1  [G, F]
        #  F   2 [G]
        #  G  1  [H]
        #  H 0
        self.assertSortAndIterate(
            {'A': ['D', 'B'],
             'B': ['C', 'F'],
             'C': ['H'],
             'D': ['H', 'E'],
             'E': ['G', 'F'],
             'F': ['G'],
             'G': ['H'],
             'H': []
             },
            'A',
            [('A', 0, (3,),  False),
             ('B', 1, (1,3,2), False),
             ('C', 1, (1,3,1), True),
             ('D', 0, (2,), False),
             ('E', 1, (1,1,2), False),
             ('F', 2, (1,2,1), True),
             ('G', 1, (1,1,1), True),
             ('H', 0, (1,), True),
             ],
            )

    def test_dotted_revnos_with_simple_merges(self):
        # A         1
        # |\
        # B C       2, 1.1.1
        # | |\
        # D E F     3, 1.1.2, 1.2.1
        # |/ /|
        # G H I     4, 1.2.2, 1.3.1
        # |/ /
        # J K       5, 1.3.2
        # |/
        # L         6
        self.assertSortAndIterate(
            {'A': [],
             'B': ['A'],
             'C': ['A'],
             'D': ['B'],
             'E': ['C'],
             'F': ['C'],
             'G': ['D', 'E'],
             'H': ['F'],
             'I': ['F'],
             'J': ['G', 'H'],
             'K': ['I'],
             'L': ['J', 'K'],
            },
            'L',
            [('L', 0, (6,), False),
             ('K', 1, (1,3,2), False),
             ('I', 1, (1,3,1), True),
             ('J', 0, (5,), False),
             ('H', 1, (1,2,2), False),
             ('F', 1, (1,2,1), True),
             ('G', 0, (4,), False),
             ('E', 1, (1,1,2), False),
             ('C', 1, (1,1,1), True),
             ('D', 0, (3,), False),
             ('B', 0, (2,), False),
             ('A', 0, (1,),  True),
             ],
            )
        # Adding a shortcut from the first revision should not change any of
        # the existing numbers
        self.assertSortAndIterate(
            {'A': [],
             'B': ['A'],
             'C': ['A'],
             'D': ['B'],
             'E': ['C'],
             'F': ['C'],
             'G': ['D', 'E'],
             'H': ['F'],
             'I': ['F'],
             'J': ['G', 'H'],
             'K': ['I'],
             'L': ['J', 'K'],
             'M': ['A'],
             'N': ['L', 'M'],
            },
            'N',
            [('N', 0, (7,), False),
             ('M', 1, (1,4,1), True),
             ('L', 0, (6,), False),
             ('K', 1, (1,3,2), False),
             ('I', 1, (1,3,1), True),
             ('J', 0, (5,), False),
             ('H', 1, (1,2,2), False),
             ('F', 1, (1,2,1), True),
             ('G', 0, (4,), False),
             ('E', 1, (1,1,2), False),
             ('C', 1, (1,1,1), True),
             ('D', 0, (3,), False),
             ('B', 0, (2,), False),
             ('A', 0, (1,),  True),
             ],
            )

    def test_end_of_merge_not_last_revision_in_branch(self):
        # within a branch only the last revision gets an
        # end of merge marker.
        self.assertSortAndIterate(
            {'A': ['B'],
             'B': [],
             },
            'A',
            [('A', 0, (2,), False),
             ('B', 0, (1,), True)
             ],
            )

    def test_end_of_merge_multiple_revisions_merged_at_once(self):
        # when multiple branches are merged at once, both of their
        # branch-endpoints should be listed as end-of-merge.
        # Also, the order of the multiple merges should be
        # left-right shown top to bottom.
        # * means end of merge
        # A 0    [H, B, E]
        # B  1   [D, C]
        # C   2  [D]       *
        # D  1   [H]       *
        # E  1   [G, F]
        # F   2  [G]       *
        # G  1   [H]       *
        # H 0    []        *
        self.assertSortAndIterate(
            {'A': ['H', 'B', 'E'],
             'B': ['D', 'C'],
             'C': ['D'],
             'D': ['H'],
             'E': ['G', 'F'],
             'F': ['G'],
             'G': ['H'],
             'H': [],
             },
            'A',
            [('A', 0, (2,), False),
             ('B', 1, (1,3,2), False),
             ('C', 2, (1,4,1), True),
             ('D', 1, (1,3,1), True),
             ('E', 1, (1,1,2), False),
             ('F', 2, (1,2,1), True),
             ('G', 1, (1,1,1), True),
             ('H', 0, (1,), True),
             ],
            )

    def test_parallel_root_sequence_numbers_increase_with_merges(self):
        """When there are parallel roots, check their revnos."""
        self.assertSortAndIterate(
            {'A': [],
             'B': [],
             'C': ['A', 'B']},
            'C',
            [('C', 0, (2,), False),
             ('B', 1, (0,1,1), True),
             ('A', 0, (1,), True),
             ],
            )

    def test_revnos_are_globally_assigned(self):
        """revnos are assigned according to the revision they derive from."""
        # in this test we setup a number of branches that all derive from
        # the first revision, and then merge them one at a time, which
        # should give the revisions as they merge numbers still deriving from
        # the revision were based on.
        # merge 3: J: ['G', 'I']
        # branch 3:
        #  I: ['H']
        #  H: ['A']
        # merge 2: G: ['D', 'F']
        # branch 2:
        #  F: ['E']
        #  E: ['A']
        # merge 1: D: ['A', 'C']
        # branch 1:
        #  C: ['B']
        #  B: ['A']
        # root: A: []
        self.assertSortAndIterate(
            {'J': ['G', 'I'],
             'I': ['H',],
             'H': ['A'],
             'G': ['D', 'F'],
             'F': ['E'],
             'E': ['A'],
             'D': ['A', 'C'],
             'C': ['B'],
             'B': ['A'],
             'A': [],
             },
            'J',
            [('J', 0, (4,), False),
             ('I', 1, (1,3,2), False),
             ('H', 1, (1,3,1), True),
             ('G', 0, (3,), False),
             ('F', 1, (1,2,2), False),
             ('E', 1, (1,2,1), True),
             ('D', 0, (2,), False),
             ('C', 1, (1,1,2), False),
             ('B', 1, (1,1,1), True),
             ('A', 0, (1,), True),
             ],
            )

    def test_roots_and_sub_branches_versus_ghosts(self):
        """Extra roots and their mini branches use the same numbering.

        All of them use the 0-node numbering.
        """
        #       A D   K
        #       | |\  |\
        #       B E F L M
        #       | |/  |/
        #       C G   N
        #       |/    |\
        #       H I   O P
        #       |/    |/
        #       J     Q
        #       |.---'
        #       R
        self.assertSortAndIterate(
            {'A': [],
             'B': ['A'],
             'C': ['B'],
             'D': [],
             'E': ['D'],
             'F': ['D'],
             'G': ['E', 'F'],
             'H': ['C', 'G'],
             'I': [],
             'J': ['H', 'I'],
             'K': [],
             'L': ['K'],
             'M': ['K'],
             'N': ['L', 'M'],
             'O': ['N'],
             'P': ['N'],
             'Q': ['O', 'P'],
             'R': ['J', 'Q'],
            },
            'R',
            [('R', 0, (6,), False),
             ('Q', 1, (0,4,5), False),
             ('P', 2, (0,6,1), True),
             ('O', 1, (0,4,4), False),
             ('N', 1, (0,4,3), False),
             ('M', 2, (0,5,1), True),
             ('L', 1, (0,4,2), False),
             ('K', 1, (0,4,1), True),
             ('J', 0, (5,), False),
             ('I', 1, (0,3,1), True),
             ('H', 0, (4,), False),
             ('G', 1, (0,1,3), False),
             ('F', 2, (0,2,1), True),
             ('E', 1, (0,1,2), False),
             ('D', 1, (0,1,1), True),
             ('C', 0, (3,), False),
             ('B', 0, (2,), False),
             ('A', 0, (1,), True),
             ],
            )

    def test_ghost(self):
        # merge_sort should be able to ignore ghosts
        # A
        # |
        # B ghost
        # |/
        # C
        self.assertSortAndIterate(
            {'A': [],
             'B': ['A'],
             'C': ['B', 'ghost'],
            },
            'C',
            [('C', 0, (3,), False),
             ('B', 0, (2,), False),
             ('A', 0, (1,), True),
            ])

    def test_lefthand_ghost(self):
        # ghost
        #  |
        #  A
        #  |
        #  B
        self.assertSortAndIterate(
            {'A': ['ghost'],
             'B': ['A'],
            }, 'B',
            [('B', 0, (2,), False),
             ('A', 0, (1,), True),
            ])

    def test_graph_cycle(self):
        # merge_sort should fail with a simple error when a graph cycle is
        # encountered.
        #
        # A
        # |,-.
        # B  |
        # |  |
        # C  ^
        # |  |
        # D  |
        # |'-'
        # E
        self.assertRaises(errors.GraphCycleError,
            self.assertSortAndIterate,
                {'A': [],
                 'B': ['D'],
                 'C': ['B'],
                 'D': ['C'],
                 'E': ['D'],
                },
                'E',
                [])


class TestKnownGraphStableReverseTopoSort(TestCaseWithKnownGraph):
    """Test the sort order returned by gc_sort."""

    def assertSorted(self, expected, parent_map):
        graph = self.make_known_graph(parent_map)
        value = graph.gc_sort()
        if expected != value:
            self.assertEqualDiff(pprint.pformat(expected),
                                 pprint.pformat(value))

    def test_empty(self):
        self.assertSorted([], {})

    def test_single(self):
        self.assertSorted(['a'], {'a':()})
        self.assertSorted([('a',)], {('a',):()})
        self.assertSorted([('F', 'a')], {('F', 'a'):()})

    def test_linear(self):
        self.assertSorted(['c', 'b', 'a'], {'a':(), 'b':('a',), 'c':('b',)})
        self.assertSorted([('c',), ('b',), ('a',)],
                          {('a',):(), ('b',): (('a',),), ('c',): (('b',),)})
        self.assertSorted([('F', 'c'), ('F', 'b'), ('F', 'a')],
                          {('F', 'a'):(), ('F', 'b'): (('F', 'a'),),
                           ('F', 'c'): (('F', 'b'),)})

    def test_mixed_ancestries(self):
        # Each prefix should be sorted separately
        self.assertSorted([('F', 'c'), ('F', 'b'), ('F', 'a'),
                           ('G', 'c'), ('G', 'b'), ('G', 'a'),
                           ('Q', 'c'), ('Q', 'b'), ('Q', 'a'),
                          ],
                          {('F', 'a'):(), ('F', 'b'): (('F', 'a'),),
                           ('F', 'c'): (('F', 'b'),),
                           ('G', 'a'):(), ('G', 'b'): (('G', 'a'),),
                           ('G', 'c'): (('G', 'b'),),
                           ('Q', 'a'):(), ('Q', 'b'): (('Q', 'a'),),
                           ('Q', 'c'): (('Q', 'b'),),
                          })

    def test_stable_sorting(self):
        # the sort order should be stable even when extra nodes are added
        self.assertSorted(['b', 'c', 'a'],
                          {'a':(), 'b':('a',), 'c':('a',)})
        self.assertSorted(['b', 'c', 'd', 'a'],
                          {'a':(), 'b':('a',), 'c':('a',), 'd':('a',)})
        self.assertSorted(['b', 'c', 'd', 'a'],
                          {'a':(), 'b':('a',), 'c':('a',), 'd':('a',)})
        self.assertSorted(['Z', 'b', 'c', 'd', 'a'],
                          {'a':(), 'b':('a',), 'c':('a',), 'd':('a',),
                           'Z':('a',)})
        self.assertSorted(['e', 'b', 'c', 'f', 'Z', 'd', 'a'],
                          {'a':(), 'b':('a',), 'c':('a',), 'd':('a',),
                           'Z':('a',),
                           'e':('b', 'c', 'd'),
                           'f':('d', 'Z'),
                           })

    def test_skip_ghost(self):
        self.assertSorted(['b', 'c', 'a'],
                          {'a':(), 'b':('a', 'ghost'), 'c':('a',)})

    def test_skip_mainline_ghost(self):
        self.assertSorted(['b', 'c', 'a'],
                          {'a':(), 'b':('ghost', 'a'), 'c':('a',)})