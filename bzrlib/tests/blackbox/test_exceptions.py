# Copyright (C) 2006, 2007 Canonical Ltd
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

"""Tests for display of exceptions."""

from cStringIO import StringIO
import os
import sys

from bzrlib import (
    bzrdir,
    config,
    errors,
    osutils,
    repository,
    tests,
    trace,
    )

from bzrlib.tests import TestCaseInTempDir, TestCase
from bzrlib.errors import NotBranchError


class TestExceptionReporting(TestCase):

    def test_exception_exitcode(self):
        # we must use a subprocess, because the normal in-memory mechanism
        # allows errors to propagate up through the test suite
        out, err = self.run_bzr_subprocess(['assert-fail'],
            universal_newlines=True,
            retcode=errors.EXIT_INTERNAL_ERROR)
        self.assertEqual(4, errors.EXIT_INTERNAL_ERROR)
        self.assertContainsRe(err,
                r'exceptions\.AssertionError: always fails\n')
        self.assertContainsRe(err, r'Bazaar has encountered an internal error')


class TestDeprecationWarning(tests.TestCaseWithTransport):
    """The deprecation warning is controlled via a global variable:
    repository._deprecation_warning_done. As such, it can be emitted only once
    during a bzr invocation, no matter how many repositories are involved.

    It would be better if it was a repo attribute instead but that's far more
    work than I want to do right now -- vila 20091215.
    """

    def setUp(self):
        super(TestDeprecationWarning, self).setUp()
        self.disable_deprecation_warning()

    def enable_deprecation_warning(self, repo=None):
        """repo is not used yet since _deprecation_warning_done is a global"""
        repository._deprecation_warning_done = False

    def disable_deprecation_warning(self, repo=None):
        """repo is not used yet since _deprecation_warning_done is a global"""
        repository._deprecation_warning_done = True

    def make_obsolete_repo(self, path):
        # We don't want the deprecation raising during the repo creation
        tree = self.make_branch_and_tree(path, format=bzrdir.BzrDirFormat5())
        return tree

    def check_warning(self, present):
        if present:
            check = self.assertContainsRe
        else:
            check = self.assertNotContainsRe
        check(self._get_log(keep_log_file=True), 'WARNING.*bzr upgrade')

    def test_repository_deprecation_warning(self):
        """Old formats give a warning"""
        self.make_obsolete_repo('foo')
        self.enable_deprecation_warning()
        out, err = self.run_bzr('status', working_dir='foo')
        self.check_warning(True)

    def test_repository_deprecation_warning_suppressed_global(self):
        """Old formats give a warning"""
        conf = config.GlobalConfig()
        conf.set_user_option('suppress_warnings', 'format_deprecation')
        self.make_obsolete_repo('foo')
        self.enable_deprecation_warning()
        out, err = self.run_bzr('status', working_dir='foo')
        self.check_warning(False)

    def test_repository_deprecation_warning_suppressed_locations(self):
        """Old formats give a warning"""
        self.make_obsolete_repo('foo')
        conf = config.LocationConfig(osutils.pathjoin(self.test_dir, 'foo'))
        conf.set_user_option('suppress_warnings', 'format_deprecation')
        self.enable_deprecation_warning()
        out, err = self.run_bzr('status', working_dir='foo')
        self.check_warning(False)

    def test_repository_deprecation_warning_suppressed_branch(self):
        """Old formats give a warning"""
        tree = self.make_obsolete_repo('foo')
        conf = tree.branch.get_config()
        conf.set_user_option('suppress_warnings', 'format_deprecation')
        self.enable_deprecation_warning()
        out, err = self.run_bzr('status', working_dir='foo')
        self.check_warning(False)

