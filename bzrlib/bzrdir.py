# Copyright (C) 2005, 2006 Canonical Ltd
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

"""BzrDir logic. The BzrDir is the basic control directory used by bzr.

At format 7 this was split out into Branch, Repository and Checkout control
directories.
"""

# TODO: remove unittest dependency; put that stuff inside the test suite

# TODO: The Format probe_transport seems a bit redundant with just trying to
# open the bzrdir. -- mbp
#
# TODO: Can we move specific formats into separate modules to make this file
# smaller?

from cStringIO import StringIO
import os
import textwrap

from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """
from copy import deepcopy
from stat import S_ISDIR
import unittest

import bzrlib
from bzrlib import (
    errors,
    lockable_files,
    lockdir,
    registry,
    revision as _mod_revision,
    repository as _mod_repository,
    symbol_versioning,
    urlutils,
    xml4,
    xml5,
    )
from bzrlib.osutils import (
    safe_unicode,
    sha_strings,
    sha_string,
    )
from bzrlib.store.revision.text import TextRevisionStore
from bzrlib.store.text import TextStore
from bzrlib.store.versioned import WeaveStore
from bzrlib.transactions import WriteTransaction
from bzrlib.transport import get_transport
from bzrlib.weave import Weave
""")

from bzrlib.trace import (
    mutter,
    note,
    )
from bzrlib.transport.local import LocalTransport


class BzrDir(object):
    """A .bzr control diretory.
    
    BzrDir instances let you create or open any of the things that can be
    found within .bzr - checkouts, branches and repositories.
    
    transport
        the transport which this bzr dir is rooted at (i.e. file:///.../.bzr/)
    root_transport
        a transport connected to the directory this bzr was opened from.
    """

    def break_lock(self):
        """Invoke break_lock on the first object in the bzrdir.

        If there is a tree, the tree is opened and break_lock() called.
        Otherwise, branch is tried, and finally repository.
        """
        try:
            thing_to_unlock = self.open_workingtree()
        except (errors.NotLocalUrl, errors.NoWorkingTree):
            try:
                thing_to_unlock = self.open_branch()
            except errors.NotBranchError:
                try:
                    thing_to_unlock = self.open_repository()
                except errors.NoRepositoryPresent:
                    return
        thing_to_unlock.break_lock()

    def can_convert_format(self):
        """Return true if this bzrdir is one whose format we can convert from."""
        return True

    def check_conversion_target(self, target_format):
        target_repo_format = target_format.repository_format
        source_repo_format = self._format.repository_format
        source_repo_format.check_conversion_target(target_repo_format)

    @staticmethod
    def _check_supported(format, allow_unsupported):
        """Check whether format is a supported format.

        If allow_unsupported is True, this is a no-op.
        """
        if not allow_unsupported and not format.is_supported():
            # see open_downlevel to open legacy branches.
            raise errors.UnsupportedFormatError(format=format)

    def clone(self, url, revision_id=None, basis=None, force_new_repo=False):
        """Clone this bzrdir and its contents to url verbatim.

        If urls last component does not exist, it will be created.

        if revision_id is not None, then the clone operation may tune
            itself to download less data.
        :param force_new_repo: Do not use a shared repository for the target 
                               even if one is available.
        """
        self._make_tail(url)
        basis_repo, basis_branch, basis_tree = self._get_basis_components(basis)
        result = self._format.initialize(url)
        try:
            local_repo = self.find_repository()
        except errors.NoRepositoryPresent:
            local_repo = None
        if local_repo:
            # may need to copy content in
            if force_new_repo:
                result_repo = local_repo.clone(
                    result,
                    revision_id=revision_id,
                    basis=basis_repo)
                result_repo.set_make_working_trees(local_repo.make_working_trees())
            else:
                try:
                    result_repo = result.find_repository()
                    # fetch content this dir needs.
                    if basis_repo:
                        # XXX FIXME RBC 20060214 need tests for this when the basis
                        # is incomplete
                        result_repo.fetch(basis_repo, revision_id=revision_id)
                    result_repo.fetch(local_repo, revision_id=revision_id)
                except errors.NoRepositoryPresent:
                    # needed to make one anyway.
                    result_repo = local_repo.clone(
                        result,
                        revision_id=revision_id,
                        basis=basis_repo)
                    result_repo.set_make_working_trees(local_repo.make_working_trees())
        # 1 if there is a branch present
        #   make sure its content is available in the target repository
        #   clone it.
        try:
            self.open_branch().clone(result, revision_id=revision_id)
        except errors.NotBranchError:
            pass
        try:
            self.open_workingtree().clone(result, basis=basis_tree)
        except (errors.NoWorkingTree, errors.NotLocalUrl):
            pass
        return result

    def _get_basis_components(self, basis):
        """Retrieve the basis components that are available at basis."""
        if basis is None:
            return None, None, None
        try:
            basis_tree = basis.open_workingtree()
            basis_branch = basis_tree.branch
            basis_repo = basis_branch.repository
        except (errors.NoWorkingTree, errors.NotLocalUrl):
            basis_tree = None
            try:
                basis_branch = basis.open_branch()
                basis_repo = basis_branch.repository
            except errors.NotBranchError:
                basis_branch = None
                try:
                    basis_repo = basis.open_repository()
                except errors.NoRepositoryPresent:
                    basis_repo = None
        return basis_repo, basis_branch, basis_tree

    # TODO: This should be given a Transport, and should chdir up; otherwise
    # this will open a new connection.
    def _make_tail(self, url):
        head, tail = urlutils.split(url)
        if tail and tail != '.':
            t = get_transport(head)
            try:
                t.mkdir(tail)
            except errors.FileExists:
                pass

    # TODO: Should take a Transport
    @classmethod
    def create(cls, base, format=None):
        """Create a new BzrDir at the url 'base'.
        
        This will call the current default formats initialize with base
        as the only parameter.

        :param format: If supplied, the format of branch to create.  If not
            supplied, the default is used.
        """
        if cls is not BzrDir:
            raise AssertionError("BzrDir.create always creates the default"
                " format, not one of %r" % cls)
        head, tail = urlutils.split(base)
        if tail and tail != '.':
            t = get_transport(head)
            try:
                t.mkdir(tail)
            except errors.FileExists:
                pass
        if format is None:
            format = BzrDirFormat.get_default_format()
        return format.initialize(safe_unicode(base))

    def create_branch(self):
        """Create a branch in this BzrDir.

        The bzrdirs format will control what branch format is created.
        For more control see BranchFormatXX.create(a_bzrdir).
        """
        raise NotImplementedError(self.create_branch)

    @staticmethod
    def create_branch_and_repo(base, force_new_repo=False, format=None):
        """Create a new BzrDir, Branch and Repository at the url 'base'.

        This will use the current default BzrDirFormat, and use whatever 
        repository format that that uses via bzrdir.create_branch and
        create_repository. If a shared repository is available that is used
        preferentially.

        The created Branch object is returned.

        :param base: The URL to create the branch at.
        :param force_new_repo: If True a new repository is always created.
        """
        bzrdir = BzrDir.create(base, format)
        bzrdir._find_or_create_repository(force_new_repo)
        return bzrdir.create_branch()

    def _find_or_create_repository(self, force_new_repo):
        """Create a new repository if needed, returning the repository."""
        if force_new_repo:
            return self.create_repository()
        try:
            return self.find_repository()
        except errors.NoRepositoryPresent:
            return self.create_repository()
        
    @staticmethod
    def create_branch_convenience(base, force_new_repo=False,
                                  force_new_tree=None, format=None):
        """Create a new BzrDir, Branch and Repository at the url 'base'.

        This is a convenience function - it will use an existing repository
        if possible, can be told explicitly whether to create a working tree or
        not.

        This will use the current default BzrDirFormat, and use whatever 
        repository format that that uses via bzrdir.create_branch and
        create_repository. If a shared repository is available that is used
        preferentially. Whatever repository is used, its tree creation policy
        is followed.

        The created Branch object is returned.
        If a working tree cannot be made due to base not being a file:// url,
        no error is raised unless force_new_tree is True, in which case no 
        data is created on disk and NotLocalUrl is raised.

        :param base: The URL to create the branch at.
        :param force_new_repo: If True a new repository is always created.
        :param force_new_tree: If True or False force creation of a tree or 
                               prevent such creation respectively.
        :param format: Override for the for the bzrdir format to create
        """
        if force_new_tree:
            # check for non local urls
            t = get_transport(safe_unicode(base))
            if not isinstance(t, LocalTransport):
                raise errors.NotLocalUrl(base)
        bzrdir = BzrDir.create(base, format)
        repo = bzrdir._find_or_create_repository(force_new_repo)
        result = bzrdir.create_branch()
        if force_new_tree or (repo.make_working_trees() and 
                              force_new_tree is None):
            try:
                bzrdir.create_workingtree()
            except errors.NotLocalUrl:
                pass
        return result
        
    @staticmethod
    def create_repository(base, shared=False, format=None):
        """Create a new BzrDir and Repository at the url 'base'.

        If no format is supplied, this will default to the current default
        BzrDirFormat by default, and use whatever repository format that that
        uses for bzrdirformat.create_repository.

        :param shared: Create a shared repository rather than a standalone
                       repository.
        The Repository object is returned.

        This must be overridden as an instance method in child classes, where
        it should take no parameters and construct whatever repository format
        that child class desires.
        """
        bzrdir = BzrDir.create(base, format)
        return bzrdir.create_repository(shared)

    @staticmethod
    def create_standalone_workingtree(base, format=None):
        """Create a new BzrDir, WorkingTree, Branch and Repository at 'base'.

        'base' must be a local path or a file:// url.

        This will use the current default BzrDirFormat, and use whatever 
        repository format that that uses for bzrdirformat.create_workingtree,
        create_branch and create_repository.

        :return: The WorkingTree object.
        """
        t = get_transport(safe_unicode(base))
        if not isinstance(t, LocalTransport):
            raise errors.NotLocalUrl(base)
        bzrdir = BzrDir.create_branch_and_repo(safe_unicode(base),
                                               force_new_repo=True,
                                               format=format).bzrdir
        return bzrdir.create_workingtree()

    def create_workingtree(self, revision_id=None):
        """Create a working tree at this BzrDir.
        
        revision_id: create it as of this revision id.
        """
        raise NotImplementedError(self.create_workingtree)

    def destroy_workingtree(self):
        """Destroy the working tree at this BzrDir.

        Formats that do not support this may raise UnsupportedOperation.
        """
        raise NotImplementedError(self.destroy_workingtree)

    def destroy_workingtree_metadata(self):
        """Destroy the control files for the working tree at this BzrDir.

        The contents of working tree files are not affected.
        Formats that do not support this may raise UnsupportedOperation.
        """
        raise NotImplementedError(self.destroy_workingtree_metadata)

    def find_repository(self):
        """Find the repository that should be used for a_bzrdir.

        This does not require a branch as we use it to find the repo for
        new branches as well as to hook existing branches up to their
        repository.
        """
        try:
            return self.open_repository()
        except errors.NoRepositoryPresent:
            pass
        next_transport = self.root_transport.clone('..')
        while True:
            # find the next containing bzrdir
            try:
                found_bzrdir = BzrDir.open_containing_from_transport(
                    next_transport)[0]
            except errors.NotBranchError:
                # none found
                raise errors.NoRepositoryPresent(self)
            # does it have a repository ?
            try:
                repository = found_bzrdir.open_repository()
            except errors.NoRepositoryPresent:
                next_transport = found_bzrdir.root_transport.clone('..')
                if (found_bzrdir.root_transport.base == next_transport.base):
                    # top of the file system
                    break
                else:
                    continue
            if ((found_bzrdir.root_transport.base == 
                 self.root_transport.base) or repository.is_shared()):
                return repository
            else:
                raise errors.NoRepositoryPresent(self)
        raise errors.NoRepositoryPresent(self)

    def get_branch_transport(self, branch_format):
        """Get the transport for use by branch format in this BzrDir.

        Note that bzr dirs that do not support format strings will raise
        IncompatibleFormat if the branch format they are given has
        a format string, and vice versa.

        If branch_format is None, the transport is returned with no 
        checking. if it is not None, then the returned transport is
        guaranteed to point to an existing directory ready for use.
        """
        raise NotImplementedError(self.get_branch_transport)
        
    def get_repository_transport(self, repository_format):
        """Get the transport for use by repository format in this BzrDir.

        Note that bzr dirs that do not support format strings will raise
        IncompatibleFormat if the repository format they are given has
        a format string, and vice versa.

        If repository_format is None, the transport is returned with no 
        checking. if it is not None, then the returned transport is
        guaranteed to point to an existing directory ready for use.
        """
        raise NotImplementedError(self.get_repository_transport)
        
    def get_workingtree_transport(self, tree_format):
        """Get the transport for use by workingtree format in this BzrDir.

        Note that bzr dirs that do not support format strings will raise
        IncompatibleFormat if the workingtree format they are given has
        a format string, and vice versa.

        If workingtree_format is None, the transport is returned with no 
        checking. if it is not None, then the returned transport is
        guaranteed to point to an existing directory ready for use.
        """
        raise NotImplementedError(self.get_workingtree_transport)
        
    def __init__(self, _transport, _format):
        """Initialize a Bzr control dir object.
        
        Only really common logic should reside here, concrete classes should be
        made with varying behaviours.

        :param _format: the format that is creating this BzrDir instance.
        :param _transport: the transport this dir is based at.
        """
        self._format = _format
        self.transport = _transport.clone('.bzr')
        self.root_transport = _transport

    def is_control_filename(self, filename):
        """True if filename is the name of a path which is reserved for bzrdir's.
        
        :param filename: A filename within the root transport of this bzrdir.

        This is true IF and ONLY IF the filename is part of the namespace reserved
        for bzr control dirs. Currently this is the '.bzr' directory in the root
        of the root_transport. it is expected that plugins will need to extend
        this in the future - for instance to make bzr talk with svn working
        trees.
        """
        # this might be better on the BzrDirFormat class because it refers to 
        # all the possible bzrdir disk formats. 
        # This method is tested via the workingtree is_control_filename tests- 
        # it was extracted from WorkingTree.is_control_filename. If the methods
        # contract is extended beyond the current trivial  implementation please
        # add new tests for it to the appropriate place.
        return filename == '.bzr' or filename.startswith('.bzr/')

    def needs_format_conversion(self, format=None):
        """Return true if this bzrdir needs convert_format run on it.
        
        For instance, if the repository format is out of date but the 
        branch and working tree are not, this should return True.

        :param format: Optional parameter indicating a specific desired
                       format we plan to arrive at.
        """
        raise NotImplementedError(self.needs_format_conversion)

    @staticmethod
    def open_unsupported(base):
        """Open a branch which is not supported."""
        return BzrDir.open(base, _unsupported=True)
        
    @staticmethod
    def open(base, _unsupported=False):
        """Open an existing bzrdir, rooted at 'base' (url)
        
        _unsupported is a private parameter to the BzrDir class.
        """
        t = get_transport(base)
        return BzrDir.open_from_transport(t, _unsupported=_unsupported)

    MAX_REDIRECTIONS = 8

    @staticmethod
    def open_from_transport(transport, _unsupported=False):
        """Open a bzrdir within a particular directory.

        :param transport: Transport containing the bzrdir.
        :param _unsupported: private.
        """
        initial_base = transport.base
        redirected = True # to enter the loop
        redirections = 0
        # If a loop occurs, there is little we can do. So we
        # don't try to detect them, just getting out if too much
        # redirections occurs. The solution is outside: where the
        # loop is defined.
        while redirected and redirections < BzrDir.MAX_REDIRECTIONS:
            try:
                format = BzrDirFormat.find_format(transport)
                redirected = False
            except errors.RedirectRequested, e:
                qualified_source = e.get_source_url()
                relpath = transport.relpath(qualified_source)
                if not e.target.endswith(relpath):
                    # Not redirected to a branch-format, not a branch
                    raise errors.NotBranchError(path=e.target)

                target = e.target[:-len(relpath)]
                note('%s is%s redirected to %s',
                     transport.base,
                     e.permanently,
                     target)
                # Let's try with a new transport 

                # FIXME: If 'transport' have a qualifier, this
                # should be applied again to the new transport
                # *iff* the schemes used are the same. It's a bit
                # tricky to verify, so I'll punt for now 
                # -- vila20070212
                qualified_target = e.get_target_url()[:-len(relpath)]
                transport = get_transport(target)
                redirections += 1
        if redirected:
            # Out of the loop and still redirected ? Either the
            # user have kept a very very very old reference to a
            # branch or a loop occured in the redirections.
            # Nothing we can cure here: tell the user. Note that
            # as the user have been informed about each
            # redirection, there is no need to issue an
            # additional error message.
            raise errors.NotBranchError(path=initial_base)
        BzrDir._check_supported(format, _unsupported)
        return format.open(transport, _found=True)

    def open_branch(self, unsupported=False):
        """Open the branch object at this BzrDir if one is present.

        If unsupported is True, then no longer supported branch formats can
        still be opened.
        
        TODO: static convenience version of this?
        """
        raise NotImplementedError(self.open_branch)

    @staticmethod
    def open_containing(url):
        """Open an existing branch which contains url.
        
        :param url: url to search from.
        See open_containing_from_transport for more detail.
        """
        return BzrDir.open_containing_from_transport(get_transport(url))
    
    @staticmethod
    def open_containing_from_transport(a_transport):
        """Open an existing branch which contains a_transport.base

        This probes for a branch at a_transport, and searches upwards from there.

        Basically we keep looking up until we find the control directory or
        run into the root.  If there isn't one, raises NotBranchError.
        If there is one and it is either an unrecognised format or an unsupported 
        format, UnknownFormatError or UnsupportedFormatError are raised.
        If there is one, it is returned, along with the unused portion of url.

        :return: The BzrDir that contains the path, and a Unicode path 
                for the rest of the URL.
        """
        # this gets the normalised url back. I.e. '.' -> the full path.
        url = a_transport.base
        while True:
            try:
                result = BzrDir.open_from_transport(a_transport)
                return result, urlutils.unescape(a_transport.relpath(url))
            except errors.NotBranchError, e:
                pass
            new_t = a_transport.clone('..')
            if new_t.base == a_transport.base:
                # reached the root, whatever that may be
                raise errors.NotBranchError(path=url)
            a_transport = new_t

    @classmethod
    def open_containing_tree_or_branch(klass, location):
        """Return the branch and working tree contained by a location.

        Returns (tree, branch, relpath).
        If there is no tree at containing the location, tree will be None.
        If there is no branch containing the location, an exception will be
        raised
        relpath is the portion of the path that is contained by the branch.
        """
        bzrdir, relpath = klass.open_containing(location)
        try:
            tree = bzrdir.open_workingtree()
        except (errors.NoWorkingTree, errors.NotLocalUrl):
            tree = None
            branch = bzrdir.open_branch()
        else:
            branch = tree.branch
        return tree, branch, relpath

    def open_repository(self, _unsupported=False):
        """Open the repository object at this BzrDir if one is present.

        This will not follow the Branch object pointer - its strictly a direct
        open facility. Most client code should use open_branch().repository to
        get at a repository.

        _unsupported is a private parameter, not part of the api.
        TODO: static convenience version of this?
        """
        raise NotImplementedError(self.open_repository)

    def open_workingtree(self, _unsupported=False):
        """Open the workingtree object at this BzrDir if one is present.
        
        TODO: static convenience version of this?
        """
        raise NotImplementedError(self.open_workingtree)

    def has_branch(self):
        """Tell if this bzrdir contains a branch.
        
        Note: if you're going to open the branch, you should just go ahead
        and try, and not ask permission first.  (This method just opens the 
        branch and discards it, and that's somewhat expensive.) 
        """
        try:
            self.open_branch()
            return True
        except errors.NotBranchError:
            return False

    def has_workingtree(self):
        """Tell if this bzrdir contains a working tree.

        This will still raise an exception if the bzrdir has a workingtree that
        is remote & inaccessible.
        
        Note: if you're going to open the working tree, you should just go ahead
        and try, and not ask permission first.  (This method just opens the 
        workingtree and discards it, and that's somewhat expensive.) 
        """
        try:
            self.open_workingtree()
            return True
        except errors.NoWorkingTree:
            return False

    def cloning_metadir(self, basis=None):
        """Produce a metadir suitable for cloning with"""
        def related_repository(bzrdir):
            try:
                branch = bzrdir.open_branch()
                return branch.repository
            except errors.NotBranchError:
                source_branch = None
                return bzrdir.open_repository()
        result_format = self._format.__class__()
        try:
            try:
                source_repository = related_repository(self)
            except errors.NoRepositoryPresent:
                if basis is None:
                    raise
                source_repository = related_repository(self)
            result_format.repository_format = source_repository._format
        except errors.NoRepositoryPresent:
            pass
        return result_format

    def sprout(self, url, revision_id=None, basis=None, force_new_repo=False):
        """Create a copy of this bzrdir prepared for use as a new line of
        development.

        If urls last component does not exist, it will be created.

        Attributes related to the identity of the source branch like
        branch nickname will be cleaned, a working tree is created
        whether one existed before or not; and a local branch is always
        created.

        if revision_id is not None, then the clone operation may tune
            itself to download less data.
        """
        self._make_tail(url)
        cloning_format = self.cloning_metadir(basis)
        result = cloning_format.initialize(url)
        basis_repo, basis_branch, basis_tree = self._get_basis_components(basis)
        try:
            source_branch = self.open_branch()
            source_repository = source_branch.repository
        except errors.NotBranchError:
            source_branch = None
            try:
                source_repository = self.open_repository()
            except errors.NoRepositoryPresent:
                # copy the entire basis one if there is one
                # but there is no repository.
                source_repository = basis_repo
        if force_new_repo:
            result_repo = None
        else:
            try:
                result_repo = result.find_repository()
            except errors.NoRepositoryPresent:
                result_repo = None
        if source_repository is None and result_repo is not None:
            pass
        elif source_repository is None and result_repo is None:
            # no repo available, make a new one
            result.create_repository()
        elif source_repository is not None and result_repo is None:
            # have source, and want to make a new target repo
            # we don't clone the repo because that preserves attributes
            # like is_shared(), and we have not yet implemented a 
            # repository sprout().
            result_repo = result.create_repository()
        if result_repo is not None:
            # fetch needed content into target.
            if basis_repo:
                # XXX FIXME RBC 20060214 need tests for this when the basis
                # is incomplete
                result_repo.fetch(basis_repo, revision_id=revision_id)
            if source_repository is not None:
                result_repo.fetch(source_repository, revision_id=revision_id)
        if source_branch is not None:
            source_branch.sprout(result, revision_id=revision_id)
        else:
            result.create_branch()
        # TODO: jam 20060426 we probably need a test in here in the
        #       case that the newly sprouted branch is a remote one
        if result_repo is None or result_repo.make_working_trees():
            wt = result.create_workingtree()
            if wt.inventory.root is None:
                try:
                    wt.set_root_id(self.open_workingtree.get_root_id())
                except errors.NoWorkingTree:
                    pass
        return result


class BzrDirPreSplitOut(BzrDir):
    """A common class for the all-in-one formats."""

    def __init__(self, _transport, _format):
        """See BzrDir.__init__."""
        super(BzrDirPreSplitOut, self).__init__(_transport, _format)
        assert self._format._lock_class == lockable_files.TransportLock
        assert self._format._lock_file_name == 'branch-lock'
        self._control_files = lockable_files.LockableFiles(
                                            self.get_branch_transport(None),
                                            self._format._lock_file_name,
                                            self._format._lock_class)

    def break_lock(self):
        """Pre-splitout bzrdirs do not suffer from stale locks."""
        raise NotImplementedError(self.break_lock)

    def clone(self, url, revision_id=None, basis=None, force_new_repo=False):
        """See BzrDir.clone()."""
        from bzrlib.workingtree import WorkingTreeFormat2
        self._make_tail(url)
        result = self._format._initialize_for_clone(url)
        basis_repo, basis_branch, basis_tree = self._get_basis_components(basis)
        self.open_repository().clone(result, revision_id=revision_id, basis=basis_repo)
        from_branch = self.open_branch()
        from_branch.clone(result, revision_id=revision_id)
        try:
            self.open_workingtree().clone(result, basis=basis_tree)
        except errors.NotLocalUrl:
            # make a new one, this format always has to have one.
            try:
                WorkingTreeFormat2().initialize(result)
            except errors.NotLocalUrl:
                # but we cannot do it for remote trees.
                to_branch = result.open_branch()
                WorkingTreeFormat2().stub_initialize_remote(to_branch.control_files)
        return result

    def create_branch(self):
        """See BzrDir.create_branch."""
        return self.open_branch()

    def create_repository(self, shared=False):
        """See BzrDir.create_repository."""
        if shared:
            raise errors.IncompatibleFormat('shared repository', self._format)
        return self.open_repository()

    def create_workingtree(self, revision_id=None):
        """See BzrDir.create_workingtree."""
        # this looks buggy but is not -really-
        # clone and sprout will have set the revision_id
        # and that will have set it for us, its only
        # specific uses of create_workingtree in isolation
        # that can do wonky stuff here, and that only
        # happens for creating checkouts, which cannot be 
        # done on this format anyway. So - acceptable wart.
        result = self.open_workingtree()
        if revision_id is not None:
            if revision_id == _mod_revision.NULL_REVISION:
                result.set_parent_ids([])
            else:
                result.set_parent_ids([revision_id])
        return result

    def destroy_workingtree(self):
        """See BzrDir.destroy_workingtree."""
        raise errors.UnsupportedOperation(self.destroy_workingtree, self)

    def destroy_workingtree_metadata(self):
        """See BzrDir.destroy_workingtree_metadata."""
        raise errors.UnsupportedOperation(self.destroy_workingtree_metadata, 
                                          self)

    def get_branch_transport(self, branch_format):
        """See BzrDir.get_branch_transport()."""
        if branch_format is None:
            return self.transport
        try:
            branch_format.get_format_string()
        except NotImplementedError:
            return self.transport
        raise errors.IncompatibleFormat(branch_format, self._format)

    def get_repository_transport(self, repository_format):
        """See BzrDir.get_repository_transport()."""
        if repository_format is None:
            return self.transport
        try:
            repository_format.get_format_string()
        except NotImplementedError:
            return self.transport
        raise errors.IncompatibleFormat(repository_format, self._format)

    def get_workingtree_transport(self, workingtree_format):
        """See BzrDir.get_workingtree_transport()."""
        if workingtree_format is None:
            return self.transport
        try:
            workingtree_format.get_format_string()
        except NotImplementedError:
            return self.transport
        raise errors.IncompatibleFormat(workingtree_format, self._format)

    def needs_format_conversion(self, format=None):
        """See BzrDir.needs_format_conversion()."""
        # if the format is not the same as the system default,
        # an upgrade is needed.
        if format is None:
            format = BzrDirFormat.get_default_format()
        return not isinstance(self._format, format.__class__)

    def open_branch(self, unsupported=False):
        """See BzrDir.open_branch."""
        from bzrlib.branch import BzrBranchFormat4
        format = BzrBranchFormat4()
        self._check_supported(format, unsupported)
        return format.open(self, _found=True)

    def sprout(self, url, revision_id=None, basis=None, force_new_repo=False):
        """See BzrDir.sprout()."""
        from bzrlib.workingtree import WorkingTreeFormat2
        self._make_tail(url)
        result = self._format._initialize_for_clone(url)
        basis_repo, basis_branch, basis_tree = self._get_basis_components(basis)
        try:
            self.open_repository().clone(result, revision_id=revision_id, basis=basis_repo)
        except errors.NoRepositoryPresent:
            pass
        try:
            self.open_branch().sprout(result, revision_id=revision_id)
        except errors.NotBranchError:
            pass
        # we always want a working tree
        WorkingTreeFormat2().initialize(result)
        return result


class BzrDir4(BzrDirPreSplitOut):
    """A .bzr version 4 control object.
    
    This is a deprecated format and may be removed after sept 2006.
    """

    def create_repository(self, shared=False):
        """See BzrDir.create_repository."""
        return self._format.repository_format.initialize(self, shared)

    def needs_format_conversion(self, format=None):
        """Format 4 dirs are always in need of conversion."""
        return True

    def open_repository(self):
        """See BzrDir.open_repository."""
        from bzrlib.repository import RepositoryFormat4
        return RepositoryFormat4().open(self, _found=True)


class BzrDir5(BzrDirPreSplitOut):
    """A .bzr version 5 control object.

    This is a deprecated format and may be removed after sept 2006.
    """

    def open_repository(self):
        """See BzrDir.open_repository."""
        from bzrlib.repository import RepositoryFormat5
        return RepositoryFormat5().open(self, _found=True)

    def open_workingtree(self, _unsupported=False):
        """See BzrDir.create_workingtree."""
        from bzrlib.workingtree import WorkingTreeFormat2
        return WorkingTreeFormat2().open(self, _found=True)


class BzrDir6(BzrDirPreSplitOut):
    """A .bzr version 6 control object.

    This is a deprecated format and may be removed after sept 2006.
    """

    def open_repository(self):
        """See BzrDir.open_repository."""
        from bzrlib.repository import RepositoryFormat6
        return RepositoryFormat6().open(self, _found=True)

    def open_workingtree(self, _unsupported=False):
        """See BzrDir.create_workingtree."""
        from bzrlib.workingtree import WorkingTreeFormat2
        return WorkingTreeFormat2().open(self, _found=True)


class BzrDirMeta1(BzrDir):
    """A .bzr meta version 1 control object.
    
    This is the first control object where the 
    individual aspects are really split out: there are separate repository,
    workingtree and branch subdirectories and any subset of the three can be
    present within a BzrDir.
    """

    def can_convert_format(self):
        """See BzrDir.can_convert_format()."""
        return True

    def create_branch(self):
        """See BzrDir.create_branch."""
        from bzrlib.branch import BranchFormat
        return BranchFormat.get_default_format().initialize(self)

    def create_repository(self, shared=False):
        """See BzrDir.create_repository."""
        return self._format.repository_format.initialize(self, shared)

    def create_workingtree(self, revision_id=None):
        """See BzrDir.create_workingtree."""
        from bzrlib.workingtree import WorkingTreeFormat
        return WorkingTreeFormat.get_default_format().initialize(self, revision_id)

    def destroy_workingtree(self):
        """See BzrDir.destroy_workingtree."""
        wt = self.open_workingtree()
        repository = wt.branch.repository
        empty = repository.revision_tree(_mod_revision.NULL_REVISION)
        wt.revert([], old_tree=empty)
        self.destroy_workingtree_metadata()

    def destroy_workingtree_metadata(self):
        self.transport.delete_tree('checkout')

    def _get_mkdir_mode(self):
        """Figure out the mode to use when creating a bzrdir subdir."""
        temp_control = lockable_files.LockableFiles(self.transport, '',
                                     lockable_files.TransportLock)
        return temp_control._dir_mode

    def get_branch_transport(self, branch_format):
        """See BzrDir.get_branch_transport()."""
        if branch_format is None:
            return self.transport.clone('branch')
        try:
            branch_format.get_format_string()
        except NotImplementedError:
            raise errors.IncompatibleFormat(branch_format, self._format)
        try:
            self.transport.mkdir('branch', mode=self._get_mkdir_mode())
        except errors.FileExists:
            pass
        return self.transport.clone('branch')

    def get_repository_transport(self, repository_format):
        """See BzrDir.get_repository_transport()."""
        if repository_format is None:
            return self.transport.clone('repository')
        try:
            repository_format.get_format_string()
        except NotImplementedError:
            raise errors.IncompatibleFormat(repository_format, self._format)
        try:
            self.transport.mkdir('repository', mode=self._get_mkdir_mode())
        except errors.FileExists:
            pass
        return self.transport.clone('repository')

    def get_workingtree_transport(self, workingtree_format):
        """See BzrDir.get_workingtree_transport()."""
        if workingtree_format is None:
            return self.transport.clone('checkout')
        try:
            workingtree_format.get_format_string()
        except NotImplementedError:
            raise errors.IncompatibleFormat(workingtree_format, self._format)
        try:
            self.transport.mkdir('checkout', mode=self._get_mkdir_mode())
        except errors.FileExists:
            pass
        return self.transport.clone('checkout')

    def needs_format_conversion(self, format=None):
        """See BzrDir.needs_format_conversion()."""
        if format is None:
            format = BzrDirFormat.get_default_format()
        if not isinstance(self._format, format.__class__):
            # it is not a meta dir format, conversion is needed.
            return True
        # we might want to push this down to the repository?
        try:
            if not isinstance(self.open_repository()._format,
                              format.repository_format.__class__):
                # the repository needs an upgrade.
                return True
        except errors.NoRepositoryPresent:
            pass
        # currently there are no other possible conversions for meta1 formats.
        return False

    def open_branch(self, unsupported=False):
        """See BzrDir.open_branch."""
        from bzrlib.branch import BranchFormat
        format = BranchFormat.find_format(self)
        self._check_supported(format, unsupported)
        return format.open(self, _found=True)

    def open_repository(self, unsupported=False):
        """See BzrDir.open_repository."""
        from bzrlib.repository import RepositoryFormat
        format = RepositoryFormat.find_format(self)
        self._check_supported(format, unsupported)
        return format.open(self, _found=True)

    def open_workingtree(self, unsupported=False):
        """See BzrDir.open_workingtree."""
        from bzrlib.workingtree import WorkingTreeFormat
        format = WorkingTreeFormat.find_format(self)
        self._check_supported(format, unsupported)
        return format.open(self, _found=True)


class BzrDirFormat(object):
    """An encapsulation of the initialization and open routines for a format.

    Formats provide three things:
     * An initialization routine,
     * a format string,
     * an open routine.

    Formats are placed in an dict by their format string for reference 
    during bzrdir opening. These should be subclasses of BzrDirFormat
    for consistency.

    Once a format is deprecated, just deprecate the initialize and open
    methods on the format class. Do not deprecate the object, as the 
    object will be created every system load.
    """

    _default_format = None
    """The default format used for new .bzr dirs."""

    _formats = {}
    """The known formats."""

    _control_formats = []
    """The registered control formats - .bzr, ....
    
    This is a list of BzrDirFormat objects.
    """

    _lock_file_name = 'branch-lock'

    # _lock_class must be set in subclasses to the lock type, typ.
    # TransportLock or LockDir

    @classmethod
    def find_format(klass, transport):
        """Return the format present at transport."""
        for format in klass._control_formats:
            try:
                return format.probe_transport(transport)
            except errors.NotBranchError:
                # this format does not find a control dir here.
                pass
        raise errors.NotBranchError(path=transport.base)

    @classmethod
    def probe_transport(klass, transport):
        """Return the .bzrdir style transport present at URL."""
        try:
            format_file = transport.get(".bzr/branch-format")
            format_string = format_file.read()
        except errors.NoSuchFile:
            raise errors.NotBranchError(path=transport.base)

        try:
            return klass._formats[format_string]
        except KeyError:
            raise errors.UnknownFormatError(format=format_string)

    @classmethod
    def get_default_format(klass):
        """Return the current default format."""
        return klass._default_format

    def get_format_string(self):
        """Return the ASCII format string that identifies this format."""
        raise NotImplementedError(self.get_format_string)

    def get_format_description(self):
        """Return the short description for this format."""
        raise NotImplementedError(self.get_format_description)

    def get_converter(self, format=None):
        """Return the converter to use to convert bzrdirs needing converts.

        This returns a bzrlib.bzrdir.Converter object.

        This should return the best upgrader to step this format towards the
        current default format. In the case of plugins we can/should provide
        some means for them to extend the range of returnable converters.

        :param format: Optional format to override the default format of the 
                       library.
        """
        raise NotImplementedError(self.get_converter)

    def initialize(self, url):
        """Create a bzr control dir at this url and return an opened copy.
        
        Subclasses should typically override initialize_on_transport
        instead of this method.
        """
        return self.initialize_on_transport(get_transport(url))

    def initialize_on_transport(self, transport):
        """Initialize a new bzrdir in the base directory of a Transport."""
        # Since we don't have a .bzr directory, inherit the
        # mode from the root directory
        temp_control = lockable_files.LockableFiles(transport,
                            '', lockable_files.TransportLock)
        temp_control._transport.mkdir('.bzr',
                                      # FIXME: RBC 20060121 don't peek under
                                      # the covers
                                      mode=temp_control._dir_mode)
        file_mode = temp_control._file_mode
        del temp_control
        mutter('created control directory in ' + transport.base)
        control = transport.clone('.bzr')
        utf8_files = [('README', 
                       "This is a Bazaar-NG control directory.\n"
                       "Do not change any files in this directory.\n"),
                      ('branch-format', self.get_format_string()),
                      ]
        # NB: no need to escape relative paths that are url safe.
        control_files = lockable_files.LockableFiles(control,
                            self._lock_file_name, self._lock_class)
        control_files.create_lock()
        control_files.lock_write()
        try:
            for file, content in utf8_files:
                control_files.put_utf8(file, content)
        finally:
            control_files.unlock()
        return self.open(transport, _found=True)

    def is_supported(self):
        """Is this format supported?

        Supported formats must be initializable and openable.
        Unsupported formats may not support initialization or committing or 
        some other features depending on the reason for not being supported.
        """
        return True

    def same_model(self, target_format):
        return (self.repository_format.rich_root_data == 
            target_format.rich_root_data)

    @classmethod
    def known_formats(klass):
        """Return all the known formats.
        
        Concrete formats should override _known_formats.
        """
        # There is double indirection here to make sure that control 
        # formats used by more than one dir format will only be probed 
        # once. This can otherwise be quite expensive for remote connections.
        result = set()
        for format in klass._control_formats:
            result.update(format._known_formats())
        return result
    
    @classmethod
    def _known_formats(klass):
        """Return the known format instances for this control format."""
        return set(klass._formats.values())

    def open(self, transport, _found=False):
        """Return an instance of this format for the dir transport points at.
        
        _found is a private parameter, do not use it.
        """
        if not _found:
            found_format = BzrDirFormat.find_format(transport)
            if not isinstance(found_format, self.__class__):
                raise AssertionError("%s was asked to open %s, but it seems to need "
                        "format %s" 
                        % (self, transport, found_format))
        return self._open(transport)

    def _open(self, transport):
        """Template method helper for opening BzrDirectories.

        This performs the actual open and any additional logic or parameter
        passing.
        """
        raise NotImplementedError(self._open)

    @classmethod
    def register_format(klass, format):
        klass._formats[format.get_format_string()] = format

    @classmethod
    def register_control_format(klass, format):
        """Register a format that does not use '.bzr' for its control dir.

        TODO: This should be pulled up into a 'ControlDirFormat' base class
        which BzrDirFormat can inherit from, and renamed to register_format 
        there. It has been done without that for now for simplicity of
        implementation.
        """
        klass._control_formats.append(format)

    @classmethod
    @symbol_versioning.deprecated_method(symbol_versioning.zero_fourteen)
    def set_default_format(klass, format):
        klass._set_default_format(format)

    @classmethod
    def _set_default_format(klass, format):
        """Set default format (for testing behavior of defaults only)"""
        klass._default_format = format

    def __str__(self):
        return self.get_format_string()[:-1]

    @classmethod
    def unregister_format(klass, format):
        assert klass._formats[format.get_format_string()] is format
        del klass._formats[format.get_format_string()]

    @classmethod
    def unregister_control_format(klass, format):
        klass._control_formats.remove(format)


class BzrDirFormat4(BzrDirFormat):
    """Bzr dir format 4.

    This format is a combined format for working tree, branch and repository.
    It has:
     - Format 1 working trees [always]
     - Format 4 branches [always]
     - Format 4 repositories [always]

    This format is deprecated: it indexes texts using a text it which is
    removed in format 5; write support for this format has been removed.
    """

    _lock_class = lockable_files.TransportLock

    def get_format_string(self):
        """See BzrDirFormat.get_format_string()."""
        return "Bazaar-NG branch, format 0.0.4\n"

    def get_format_description(self):
        """See BzrDirFormat.get_format_description()."""
        return "All-in-one format 4"

    def get_converter(self, format=None):
        """See BzrDirFormat.get_converter()."""
        # there is one and only one upgrade path here.
        return ConvertBzrDir4To5()
        
    def initialize_on_transport(self, transport):
        """Format 4 branches cannot be created."""
        raise errors.UninitializableFormat(self)

    def is_supported(self):
        """Format 4 is not supported.

        It is not supported because the model changed from 4 to 5 and the
        conversion logic is expensive - so doing it on the fly was not 
        feasible.
        """
        return False

    def _open(self, transport):
        """See BzrDirFormat._open."""
        return BzrDir4(transport, self)

    def __return_repository_format(self):
        """Circular import protection."""
        from bzrlib.repository import RepositoryFormat4
        return RepositoryFormat4()
    repository_format = property(__return_repository_format)


class BzrDirFormat5(BzrDirFormat):
    """Bzr control format 5.

    This format is a combined format for working tree, branch and repository.
    It has:
     - Format 2 working trees [always] 
     - Format 4 branches [always] 
     - Format 5 repositories [always]
       Unhashed stores in the repository.
    """

    _lock_class = lockable_files.TransportLock

    def get_format_string(self):
        """See BzrDirFormat.get_format_string()."""
        return "Bazaar-NG branch, format 5\n"

    def get_format_description(self):
        """See BzrDirFormat.get_format_description()."""
        return "All-in-one format 5"

    def get_converter(self, format=None):
        """See BzrDirFormat.get_converter()."""
        # there is one and only one upgrade path here.
        return ConvertBzrDir5To6()

    def _initialize_for_clone(self, url):
        return self.initialize_on_transport(get_transport(url), _cloning=True)
        
    def initialize_on_transport(self, transport, _cloning=False):
        """Format 5 dirs always have working tree, branch and repository.
        
        Except when they are being cloned.
        """
        from bzrlib.branch import BzrBranchFormat4
        from bzrlib.repository import RepositoryFormat5
        from bzrlib.workingtree import WorkingTreeFormat2
        result = (super(BzrDirFormat5, self).initialize_on_transport(transport))
        RepositoryFormat5().initialize(result, _internal=True)
        if not _cloning:
            branch = BzrBranchFormat4().initialize(result)
            try:
                WorkingTreeFormat2().initialize(result)
            except errors.NotLocalUrl:
                # Even though we can't access the working tree, we need to
                # create its control files.
                WorkingTreeFormat2().stub_initialize_remote(branch.control_files)
        return result

    def _open(self, transport):
        """See BzrDirFormat._open."""
        return BzrDir5(transport, self)

    def __return_repository_format(self):
        """Circular import protection."""
        from bzrlib.repository import RepositoryFormat5
        return RepositoryFormat5()
    repository_format = property(__return_repository_format)


class BzrDirFormat6(BzrDirFormat):
    """Bzr control format 6.

    This format is a combined format for working tree, branch and repository.
    It has:
     - Format 2 working trees [always] 
     - Format 4 branches [always] 
     - Format 6 repositories [always]
    """

    _lock_class = lockable_files.TransportLock

    def get_format_string(self):
        """See BzrDirFormat.get_format_string()."""
        return "Bazaar-NG branch, format 6\n"

    def get_format_description(self):
        """See BzrDirFormat.get_format_description()."""
        return "All-in-one format 6"

    def get_converter(self, format=None):
        """See BzrDirFormat.get_converter()."""
        # there is one and only one upgrade path here.
        return ConvertBzrDir6ToMeta()
        
    def _initialize_for_clone(self, url):
        return self.initialize_on_transport(get_transport(url), _cloning=True)

    def initialize_on_transport(self, transport, _cloning=False):
        """Format 6 dirs always have working tree, branch and repository.
        
        Except when they are being cloned.
        """
        from bzrlib.branch import BzrBranchFormat4
        from bzrlib.repository import RepositoryFormat6
        from bzrlib.workingtree import WorkingTreeFormat2
        result = super(BzrDirFormat6, self).initialize_on_transport(transport)
        RepositoryFormat6().initialize(result, _internal=True)
        if not _cloning:
            branch = BzrBranchFormat4().initialize(result)
            try:
                WorkingTreeFormat2().initialize(result)
            except errors.NotLocalUrl:
                # Even though we can't access the working tree, we need to
                # create its control files.
                WorkingTreeFormat2().stub_initialize_remote(branch.control_files)
        return result

    def _open(self, transport):
        """See BzrDirFormat._open."""
        return BzrDir6(transport, self)

    def __return_repository_format(self):
        """Circular import protection."""
        from bzrlib.repository import RepositoryFormat6
        return RepositoryFormat6()
    repository_format = property(__return_repository_format)


class BzrDirMetaFormat1(BzrDirFormat):
    """Bzr meta control format 1

    This is the first format with split out working tree, branch and repository
    disk storage.
    It has:
     - Format 3 working trees [optional]
     - Format 5 branches [optional]
     - Format 7 repositories [optional]
    """

    _lock_class = lockdir.LockDir

    def get_converter(self, format=None):
        """See BzrDirFormat.get_converter()."""
        if format is None:
            format = BzrDirFormat.get_default_format()
        if not isinstance(self, format.__class__):
            # converting away from metadir is not implemented
            raise NotImplementedError(self.get_converter)
        return ConvertMetaToMeta(format)

    def get_format_string(self):
        """See BzrDirFormat.get_format_string()."""
        return "Bazaar-NG meta directory, format 1\n"

    def get_format_description(self):
        """See BzrDirFormat.get_format_description()."""
        return "Meta directory format 1"

    def _open(self, transport):
        """See BzrDirFormat._open."""
        return BzrDirMeta1(transport, self)

    def __return_repository_format(self):
        """Circular import protection."""
        if getattr(self, '_repository_format', None):
            return self._repository_format
        from bzrlib.repository import RepositoryFormat
        return RepositoryFormat.get_default_format()

    def __set_repository_format(self, value):
        """Allow changint the repository format for metadir formats."""
        self._repository_format = value

    repository_format = property(__return_repository_format, __set_repository_format)


# register BzrDirMetaFormat1 as a control format. Our only
# concrete control format (BzrDirFormat is an abstract one).
BzrDirFormat.register_control_format(BzrDirMetaFormat1)

# Register bzr formats
BzrDirFormat.register_format(BzrDirFormat4())
BzrDirFormat.register_format(BzrDirFormat5())
BzrDirFormat.register_format(BzrDirFormat6())
__default_format = BzrDirMetaFormat1()
BzrDirFormat.register_format(__default_format)
BzrDirFormat._default_format = __default_format


class BzrDirTestProviderAdapter(object):
    """A tool to generate a suite testing multiple bzrdir formats at once.

    This is done by copying the test once for each transport and injecting
    the transport_server, transport_readonly_server, and bzrdir_format
    classes into each copy. Each copy is also given a new id() to make it
    easy to identify.
    """

    def __init__(self, transport_server, transport_readonly_server, formats):
        self._transport_server = transport_server
        self._transport_readonly_server = transport_readonly_server
        self._formats = formats
    
    def adapt(self, test):
        result = unittest.TestSuite()
        for format in self._formats:
            new_test = deepcopy(test)
            new_test.transport_server = self._transport_server
            new_test.transport_readonly_server = self._transport_readonly_server
            new_test.bzrdir_format = format
            def make_new_test_id():
                new_id = "%s(%s)" % (new_test.id(), format.__class__.__name__)
                return lambda: new_id
            new_test.id = make_new_test_id()
            result.addTest(new_test)
        return result


class Converter(object):
    """Converts a disk format object from one format to another."""

    def convert(self, to_convert, pb):
        """Perform the conversion of to_convert, giving feedback via pb.

        :param to_convert: The disk object to convert.
        :param pb: a progress bar to use for progress information.
        """

    def step(self, message):
        """Update the pb by a step."""
        self.count +=1
        self.pb.update(message, self.count, self.total)


class ConvertBzrDir4To5(Converter):
    """Converts format 4 bzr dirs to format 5."""

    def __init__(self):
        super(ConvertBzrDir4To5, self).__init__()
        self.converted_revs = set()
        self.absent_revisions = set()
        self.text_count = 0
        self.revisions = {}
        
    def convert(self, to_convert, pb):
        """See Converter.convert()."""
        self.bzrdir = to_convert
        self.pb = pb
        self.pb.note('starting upgrade from format 4 to 5')
        if isinstance(self.bzrdir.transport, LocalTransport):
            self.bzrdir.get_workingtree_transport(None).delete('stat-cache')
        self._convert_to_weaves()
        return BzrDir.open(self.bzrdir.root_transport.base)

    def _convert_to_weaves(self):
        self.pb.note('note: upgrade may be faster if all store files are ungzipped first')
        try:
            # TODO permissions
            stat = self.bzrdir.transport.stat('weaves')
            if not S_ISDIR(stat.st_mode):
                self.bzrdir.transport.delete('weaves')
                self.bzrdir.transport.mkdir('weaves')
        except errors.NoSuchFile:
            self.bzrdir.transport.mkdir('weaves')
        # deliberately not a WeaveFile as we want to build it up slowly.
        self.inv_weave = Weave('inventory')
        # holds in-memory weaves for all files
        self.text_weaves = {}
        self.bzrdir.transport.delete('branch-format')
        self.branch = self.bzrdir.open_branch()
        self._convert_working_inv()
        rev_history = self.branch.revision_history()
        # to_read is a stack holding the revisions we still need to process;
        # appending to it adds new highest-priority revisions
        self.known_revisions = set(rev_history)
        self.to_read = rev_history[-1:]
        while self.to_read:
            rev_id = self.to_read.pop()
            if (rev_id not in self.revisions
                and rev_id not in self.absent_revisions):
                self._load_one_rev(rev_id)
        self.pb.clear()
        to_import = self._make_order()
        for i, rev_id in enumerate(to_import):
            self.pb.update('converting revision', i, len(to_import))
            self._convert_one_rev(rev_id)
        self.pb.clear()
        self._write_all_weaves()
        self._write_all_revs()
        self.pb.note('upgraded to weaves:')
        self.pb.note('  %6d revisions and inventories', len(self.revisions))
        self.pb.note('  %6d revisions not present', len(self.absent_revisions))
        self.pb.note('  %6d texts', self.text_count)
        self._cleanup_spare_files_after_format4()
        self.branch.control_files.put_utf8('branch-format', BzrDirFormat5().get_format_string())

    def _cleanup_spare_files_after_format4(self):
        # FIXME working tree upgrade foo.
        for n in 'merged-patches', 'pending-merged-patches':
            try:
                ## assert os.path.getsize(p) == 0
                self.bzrdir.transport.delete(n)
            except errors.NoSuchFile:
                pass
        self.bzrdir.transport.delete_tree('inventory-store')
        self.bzrdir.transport.delete_tree('text-store')

    def _convert_working_inv(self):
        inv = xml4.serializer_v4.read_inventory(
                    self.branch.control_files.get('inventory'))
        new_inv_xml = xml5.serializer_v5.write_inventory_to_string(inv)
        # FIXME inventory is a working tree change.
        self.branch.control_files.put('inventory', StringIO(new_inv_xml))

    def _write_all_weaves(self):
        controlweaves = WeaveStore(self.bzrdir.transport, prefixed=False)
        weave_transport = self.bzrdir.transport.clone('weaves')
        weaves = WeaveStore(weave_transport, prefixed=False)
        transaction = WriteTransaction()

        try:
            i = 0
            for file_id, file_weave in self.text_weaves.items():
                self.pb.update('writing weave', i, len(self.text_weaves))
                weaves._put_weave(file_id, file_weave, transaction)
                i += 1
            self.pb.update('inventory', 0, 1)
            controlweaves._put_weave('inventory', self.inv_weave, transaction)
            self.pb.update('inventory', 1, 1)
        finally:
            self.pb.clear()

    def _write_all_revs(self):
        """Write all revisions out in new form."""
        self.bzrdir.transport.delete_tree('revision-store')
        self.bzrdir.transport.mkdir('revision-store')
        revision_transport = self.bzrdir.transport.clone('revision-store')
        # TODO permissions
        _revision_store = TextRevisionStore(TextStore(revision_transport,
                                                      prefixed=False,
                                                      compressed=True))
        try:
            transaction = WriteTransaction()
            for i, rev_id in enumerate(self.converted_revs):
                self.pb.update('write revision', i, len(self.converted_revs))
                _revision_store.add_revision(self.revisions[rev_id], transaction)
        finally:
            self.pb.clear()
            
    def _load_one_rev(self, rev_id):
        """Load a revision object into memory.

        Any parents not either loaded or abandoned get queued to be
        loaded."""
        self.pb.update('loading revision',
                       len(self.revisions),
                       len(self.known_revisions))
        if not self.branch.repository.has_revision(rev_id):
            self.pb.clear()
            self.pb.note('revision {%s} not present in branch; '
                         'will be converted as a ghost',
                         rev_id)
            self.absent_revisions.add(rev_id)
        else:
            rev = self.branch.repository._revision_store.get_revision(rev_id,
                self.branch.repository.get_transaction())
            for parent_id in rev.parent_ids:
                self.known_revisions.add(parent_id)
                self.to_read.append(parent_id)
            self.revisions[rev_id] = rev

    def _load_old_inventory(self, rev_id):
        assert rev_id not in self.converted_revs
        old_inv_xml = self.branch.repository.inventory_store.get(rev_id).read()
        inv = xml4.serializer_v4.read_inventory_from_string(old_inv_xml)
        inv.revision_id = rev_id
        rev = self.revisions[rev_id]
        if rev.inventory_sha1:
            assert rev.inventory_sha1 == sha_string(old_inv_xml), \
                'inventory sha mismatch for {%s}' % rev_id
        return inv

    def _load_updated_inventory(self, rev_id):
        assert rev_id in self.converted_revs
        inv_xml = self.inv_weave.get_text(rev_id)
        inv = xml5.serializer_v5.read_inventory_from_string(inv_xml)
        return inv

    def _convert_one_rev(self, rev_id):
        """Convert revision and all referenced objects to new format."""
        rev = self.revisions[rev_id]
        inv = self._load_old_inventory(rev_id)
        present_parents = [p for p in rev.parent_ids
                           if p not in self.absent_revisions]
        self._convert_revision_contents(rev, inv, present_parents)
        self._store_new_weave(rev, inv, present_parents)
        self.converted_revs.add(rev_id)

    def _store_new_weave(self, rev, inv, present_parents):
        # the XML is now updated with text versions
        if __debug__:
            entries = inv.iter_entries()
            entries.next()
            for path, ie in entries:
                assert getattr(ie, 'revision', None) is not None, \
                    'no revision on {%s} in {%s}' % \
                    (file_id, rev.revision_id)
        new_inv_xml = xml5.serializer_v5.write_inventory_to_string(inv)
        new_inv_sha1 = sha_string(new_inv_xml)
        self.inv_weave.add_lines(rev.revision_id, 
                                 present_parents,
                                 new_inv_xml.splitlines(True))
        rev.inventory_sha1 = new_inv_sha1

    def _convert_revision_contents(self, rev, inv, present_parents):
        """Convert all the files within a revision.

        Also upgrade the inventory to refer to the text revision ids."""
        rev_id = rev.revision_id
        mutter('converting texts of revision {%s}',
               rev_id)
        parent_invs = map(self._load_updated_inventory, present_parents)
        entries = inv.iter_entries()
        entries.next()
        for path, ie in entries:
            self._convert_file_version(rev, ie, parent_invs)

    def _convert_file_version(self, rev, ie, parent_invs):
        """Convert one version of one file.

        The file needs to be added into the weave if it is a merge
        of >=2 parents or if it's changed from its parent.
        """
        file_id = ie.file_id
        rev_id = rev.revision_id
        w = self.text_weaves.get(file_id)
        if w is None:
            w = Weave(file_id)
            self.text_weaves[file_id] = w
        text_changed = False
        previous_entries = ie.find_previous_heads(parent_invs,
                                                  None,
                                                  None,
                                                  entry_vf=w)
        for old_revision in previous_entries:
                # if this fails, its a ghost ?
                assert old_revision in self.converted_revs, \
                    "Revision {%s} not in converted_revs" % old_revision
        self.snapshot_ie(previous_entries, ie, w, rev_id)
        del ie.text_id
        assert getattr(ie, 'revision', None) is not None

    def snapshot_ie(self, previous_revisions, ie, w, rev_id):
        # TODO: convert this logic, which is ~= snapshot to
        # a call to:. This needs the path figured out. rather than a work_tree
        # a v4 revision_tree can be given, or something that looks enough like
        # one to give the file content to the entry if it needs it.
        # and we need something that looks like a weave store for snapshot to 
        # save against.
        #ie.snapshot(rev, PATH, previous_revisions, REVISION_TREE, InMemoryWeaveStore(self.text_weaves))
        if len(previous_revisions) == 1:
            previous_ie = previous_revisions.values()[0]
            if ie._unchanged(previous_ie):
                ie.revision = previous_ie.revision
                return
        if ie.has_text():
            text = self.branch.repository.text_store.get(ie.text_id)
            file_lines = text.readlines()
            assert sha_strings(file_lines) == ie.text_sha1
            assert sum(map(len, file_lines)) == ie.text_size
            w.add_lines(rev_id, previous_revisions, file_lines)
            self.text_count += 1
        else:
            w.add_lines(rev_id, previous_revisions, [])
        ie.revision = rev_id

    def _make_order(self):
        """Return a suitable order for importing revisions.

        The order must be such that an revision is imported after all
        its (present) parents.
        """
        todo = set(self.revisions.keys())
        done = self.absent_revisions.copy()
        order = []
        while todo:
            # scan through looking for a revision whose parents
            # are all done
            for rev_id in sorted(list(todo)):
                rev = self.revisions[rev_id]
                parent_ids = set(rev.parent_ids)
                if parent_ids.issubset(done):
                    # can take this one now
                    order.append(rev_id)
                    todo.remove(rev_id)
                    done.add(rev_id)
        return order


class ConvertBzrDir5To6(Converter):
    """Converts format 5 bzr dirs to format 6."""

    def convert(self, to_convert, pb):
        """See Converter.convert()."""
        self.bzrdir = to_convert
        self.pb = pb
        self.pb.note('starting upgrade from format 5 to 6')
        self._convert_to_prefixed()
        return BzrDir.open(self.bzrdir.root_transport.base)

    def _convert_to_prefixed(self):
        from bzrlib.store import TransportStore
        self.bzrdir.transport.delete('branch-format')
        for store_name in ["weaves", "revision-store"]:
            self.pb.note("adding prefixes to %s" % store_name)
            store_transport = self.bzrdir.transport.clone(store_name)
            store = TransportStore(store_transport, prefixed=True)
            for urlfilename in store_transport.list_dir('.'):
                filename = urlutils.unescape(urlfilename)
                if (filename.endswith(".weave") or
                    filename.endswith(".gz") or
                    filename.endswith(".sig")):
                    file_id = os.path.splitext(filename)[0]
                else:
                    file_id = filename
                prefix_dir = store.hash_prefix(file_id)
                # FIXME keep track of the dirs made RBC 20060121
                try:
                    store_transport.move(filename, prefix_dir + '/' + filename)
                except errors.NoSuchFile: # catches missing dirs strangely enough
                    store_transport.mkdir(prefix_dir)
                    store_transport.move(filename, prefix_dir + '/' + filename)
        self.bzrdir._control_files.put_utf8('branch-format', BzrDirFormat6().get_format_string())


class ConvertBzrDir6ToMeta(Converter):
    """Converts format 6 bzr dirs to metadirs."""

    def convert(self, to_convert, pb):
        """See Converter.convert()."""
        from bzrlib.branch import BzrBranchFormat5
        self.bzrdir = to_convert
        self.pb = pb
        self.count = 0
        self.total = 20 # the steps we know about
        self.garbage_inventories = []

        self.pb.note('starting upgrade from format 6 to metadir')
        self.bzrdir._control_files.put_utf8('branch-format', "Converting to format 6")
        # its faster to move specific files around than to open and use the apis...
        # first off, nuke ancestry.weave, it was never used.
        try:
            self.step('Removing ancestry.weave')
            self.bzrdir.transport.delete('ancestry.weave')
        except errors.NoSuchFile:
            pass
        # find out whats there
        self.step('Finding branch files')
        last_revision = self.bzrdir.open_branch().last_revision()
        bzrcontents = self.bzrdir.transport.list_dir('.')
        for name in bzrcontents:
            if name.startswith('basis-inventory.'):
                self.garbage_inventories.append(name)
        # create new directories for repository, working tree and branch
        self.dir_mode = self.bzrdir._control_files._dir_mode
        self.file_mode = self.bzrdir._control_files._file_mode
        repository_names = [('inventory.weave', True),
                            ('revision-store', True),
                            ('weaves', True)]
        self.step('Upgrading repository  ')
        self.bzrdir.transport.mkdir('repository', mode=self.dir_mode)
        self.make_lock('repository')
        # we hard code the formats here because we are converting into
        # the meta format. The meta format upgrader can take this to a 
        # future format within each component.
        self.put_format('repository', _mod_repository.RepositoryFormat7())
        for entry in repository_names:
            self.move_entry('repository', entry)

        self.step('Upgrading branch      ')
        self.bzrdir.transport.mkdir('branch', mode=self.dir_mode)
        self.make_lock('branch')
        self.put_format('branch', BzrBranchFormat5())
        branch_files = [('revision-history', True),
                        ('branch-name', True),
                        ('parent', False)]
        for entry in branch_files:
            self.move_entry('branch', entry)

        checkout_files = [('pending-merges', True),
                          ('inventory', True),
                          ('stat-cache', False)]
        # If a mandatory checkout file is not present, the branch does not have
        # a functional checkout. Do not create a checkout in the converted
        # branch.
        for name, mandatory in checkout_files:
            if mandatory and name not in bzrcontents:
                has_checkout = False
                break
        else:
            has_checkout = True
        if not has_checkout:
            self.pb.note('No working tree.')
            # If some checkout files are there, we may as well get rid of them.
            for name, mandatory in checkout_files:
                if name in bzrcontents:
                    self.bzrdir.transport.delete(name)
        else:
            from bzrlib.workingtree import WorkingTreeFormat3
            self.step('Upgrading working tree')
            self.bzrdir.transport.mkdir('checkout', mode=self.dir_mode)
            self.make_lock('checkout')
            self.put_format(
                'checkout', WorkingTreeFormat3())
            self.bzrdir.transport.delete_multi(
                self.garbage_inventories, self.pb)
            for entry in checkout_files:
                self.move_entry('checkout', entry)
            if last_revision is not None:
                self.bzrdir._control_files.put_utf8(
                    'checkout/last-revision', last_revision)
        self.bzrdir._control_files.put_utf8(
            'branch-format', BzrDirMetaFormat1().get_format_string())
        return BzrDir.open(self.bzrdir.root_transport.base)

    def make_lock(self, name):
        """Make a lock for the new control dir name."""
        self.step('Make %s lock' % name)
        ld = lockdir.LockDir(self.bzrdir.transport,
                             '%s/lock' % name,
                             file_modebits=self.file_mode,
                             dir_modebits=self.dir_mode)
        ld.create()

    def move_entry(self, new_dir, entry):
        """Move then entry name into new_dir."""
        name = entry[0]
        mandatory = entry[1]
        self.step('Moving %s' % name)
        try:
            self.bzrdir.transport.move(name, '%s/%s' % (new_dir, name))
        except errors.NoSuchFile:
            if mandatory:
                raise

    def put_format(self, dirname, format):
        self.bzrdir._control_files.put_utf8('%s/format' % dirname, format.get_format_string())


class ConvertMetaToMeta(Converter):
    """Converts the components of metadirs."""

    def __init__(self, target_format):
        """Create a metadir to metadir converter.

        :param target_format: The final metadir format that is desired.
        """
        self.target_format = target_format

    def convert(self, to_convert, pb):
        """See Converter.convert()."""
        self.bzrdir = to_convert
        self.pb = pb
        self.count = 0
        self.total = 1
        self.step('checking repository format')
        try:
            repo = self.bzrdir.open_repository()
        except errors.NoRepositoryPresent:
            pass
        else:
            if not isinstance(repo._format, self.target_format.repository_format.__class__):
                from bzrlib.repository import CopyConverter
                self.pb.note('starting repository conversion')
                converter = CopyConverter(self.target_format.repository_format)
                converter.convert(repo, pb)
        return to_convert


class BzrDirFormatInfo(object):

    def __init__(self, native, deprecated):
        self.deprecated = deprecated
        self.native = native


class BzrDirFormatRegistry(registry.Registry):
    """Registry of user-selectable BzrDir subformats.
    
    Differs from BzrDirFormat._control_formats in that it provides sub-formats,
    e.g. BzrDirMeta1 with weave repository.  Also, it's more user-oriented.
    """

    def register_metadir(self, key, repo, help, native=True, deprecated=False):
        """Register a metadir subformat.
        
        repo is the repository format name as a string.
        """
        # This should be expanded to support setting WorkingTree and Branch
        # formats, once BzrDirMetaFormat1 supports that.
        def helper():
            import bzrlib.repository
            repo_format = getattr(bzrlib.repository, repo)
            bd = BzrDirMetaFormat1()
            bd.repository_format = repo_format()
            return bd
        self.register(key, helper, help, native, deprecated)

    def register(self, key, factory, help, native=True, deprecated=False):
        """Register a BzrDirFormat factory.
        
        The factory must be a callable that takes one parameter: the key.
        It must produce an instance of the BzrDirFormat when called.

        This function mainly exists to prevent the info object from being
        supplied directly.
        """
        registry.Registry.register(self, key, factory, help, 
            BzrDirFormatInfo(native, deprecated))

    def register_lazy(self, key, module_name, member_name, help, native=True,
                      deprecated=False):
        registry.Registry.register_lazy(self, key, module_name, member_name, 
            help, BzrDirFormatInfo(native, deprecated))

    def set_default(self, key):
        """Set the 'default' key to be a clone of the supplied key.
        
        This method must be called once and only once.
        """
        registry.Registry.register(self, 'default', self.get(key), 
            self.get_help(key), info=self.get_info(key))

    def set_default_repository(self, key):
        """Set the FormatRegistry default and Repository default.
        
        This is a transitional method while Repository.set_default_format
        is deprecated.
        """
        if 'default' in self:
            self.remove('default')
        self.set_default(key)
        format = self.get('default')()
        assert isinstance(format, BzrDirMetaFormat1)
        from bzrlib import repository
        repository.RepositoryFormat._set_default_format(
            format.repository_format)

    def make_bzrdir(self, key):
        return self.get(key)()

    def help_topic(self, topic):
        output = textwrap.dedent("""\
            Bazaar directory formats
            ------------------------

            These formats can be used for creating branches, working trees, and
            repositories.

            """)
        default_help = self.get_help('default')
        help_pairs = []
        for key in self.keys():
            if key == 'default':
                continue
            help = self.get_help(key)
            if help == default_help:
                default_realkey = key
            else:
                help_pairs.append((key, help))

        def wrapped(key, help, info):
            if info.native:
                help = '(native) ' + help
            return '  %s:\n%s\n\n' % (key, 
                    textwrap.fill(help, initial_indent='    ', 
                    subsequent_indent='    '))
        output += wrapped('%s/default' % default_realkey, default_help,
                          self.get_info('default'))
        deprecated_pairs = []
        for key, help in help_pairs:
            info = self.get_info(key)
            if info.deprecated:
                deprecated_pairs.append((key, help))
            else:
                output += wrapped(key, help, info)
        if len(deprecated_pairs) > 0:
            output += "Deprecated formats\n------------------\n\n"
            for key, help in deprecated_pairs:
                info = self.get_info(key)
                output += wrapped(key, help, info)

        return output


format_registry = BzrDirFormatRegistry()
format_registry.register('weave', BzrDirFormat6,
    'Pre-0.8 format.  Slower than knit and does not'
    ' support checkouts or shared repositories.', deprecated=True)
format_registry.register_metadir('knit', 'RepositoryFormatKnit1',
    'Format using knits.  Recommended.')
format_registry.set_default('knit')
format_registry.register_metadir('metaweave', 'RepositoryFormat7',
    'Transitional format in 0.8.  Slower than knit.',
    deprecated=True)
format_registry.register_metadir('experimental-knit2', 'RepositoryFormatKnit2',
    'Experimental successor to knit.  Use at your own risk.')
