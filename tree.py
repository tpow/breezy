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


"""Git Trees."""

from __future__ import absolute_import

from dulwich.object_store import (
    tree_lookup_path,
    OverlayObjectStore,
    )
import stat
import posixpath

from ... import (
    delta,
    errors,
    osutils,
    revisiontree,
    tree,
    )
from ...revision import NULL_REVISION
from ...bzr import (
    inventory,
    )

from .mapping import (
    mode_is_executable,
    mode_kind,
    GitFileIdMap,
    default_mapping,
    )


class GitRevisionTree(revisiontree.RevisionTree):
    """Revision tree implementation based on Git objects."""

    def __init__(self, repository, revision_id):
        self._revision_id = revision_id
        self._repository = repository
        self.store = repository._git.object_store
        assert isinstance(revision_id, str)
        self.commit_id, self.mapping = repository.lookup_bzr_revision_id(revision_id)
        if revision_id == NULL_REVISION:
            self.tree = None
            self.mapping = default_mapping
            self._fileid_map = GitFileIdMap(
                {},
                default_mapping)
        else:
            try:
                commit = self.store[self.commit_id]
            except KeyError, r:
                raise errors.NoSuchRevision(repository, revision_id)
            self.tree = commit.tree
            self._fileid_map = self.mapping.get_fileid_map(self.store.__getitem__, self.tree)

    def get_file_revision(self, path, file_id=None):
        change_scanner = self._repository._file_change_scanner
        (path, commit_id) = change_scanner.find_last_change_revision(
            path.encode('utf-8'), self.commit_id)
        return self._repository.lookup_foreign_revision_id(commit_id, self.mapping)

    def get_file_mtime(self, path, file_id=None):
        revid = self.get_file_revision(path, file_id)
        try:
            rev = self._repository.get_revision(revid)
        except errors.NoSuchRevision:
            raise errors.FileTimestampUnavailable(path)
        return rev.timestamp

    def id2path(self, file_id):
        try:
            path = self._fileid_map.lookup_path(file_id)
        except ValueError:
            raise errors.NoSuchId(self, file_id)
        path = path.decode('utf-8')
        if self.has_filename(path):
            return path
        raise errors.NoSuchId(self, file_id)

    def is_versioned(self, path):
        return self.has_filename(path)

    def path2id(self, path):
        if self.mapping.is_special_file(path):
            return None
        return self._fileid_map.lookup_file_id(path.encode('utf-8'))

    def all_file_ids(self):
        return set(self._fileid_map.all_file_ids())

    def all_versioned_paths(self):
        ret = set()
        todo = set([('', self.tree)])
        while todo:
            (path, tree_id) = todo.pop()
            if tree_id is None:
                continue
            tree = self.store[tree_id]
            for name, mode, hexsha in tree.iteritems():
                subpath = posixpath.join(path, name)
                if stat.S_ISDIR(mode):
                    todo.add((subpath, hexsha))
                else:
                    ret.add(subpath)
        return ret

    def get_root_id(self):
        return self.path2id("")

    def has_or_had_id(self, file_id):
        return self.has_id(file_id)

    def has_id(self, file_id):
        try:
            path = self.id2path(file_id)
        except errors.NoSuchId:
            return False
        return self.has_filename(path)

    def is_executable(self, path, file_id=None):
        try:
            (mode, hexsha) = tree_lookup_path(self.store.__getitem__, self.tree,
                path)
        except KeyError:
            raise errors.NoSuchId(self, path)
        if mode is None:
            # the tree root is a directory
            return False
        return mode_is_executable(mode)

    def kind(self, path, file_id=None):
        if self.tree is None:
            raise errors.NoSuchFile(path)
        try:
            (mode, hexsha) = tree_lookup_path(self.store.__getitem__, self.tree,
                path)
        except KeyError:
            raise errors.NoSuchFile(path)
        if mode is None:
            # the tree root is a directory
            return "directory"
        return mode_kind(mode)

    def has_filename(self, path):
        if self.tree is None:
            return False
        try:
            tree_lookup_path(self.store.__getitem__, self.tree,
                path.encode("utf-8"))
        except KeyError:
            return False
        else:
            return True

    def list_files(self, include_root=False, from_dir=None, recursive=True):
        if from_dir is None:
            from_dir = u""
        if self.tree is None:
            return
        (mode, hexsha) = tree_lookup_path(self.store.__getitem__, self.tree,
            from_dir.encode("utf-8"))
        if mode is None: # Root
            root_ie = self._get_dir_ie(b"", None)
        else:
            parent_path = posixpath.dirname(from_dir.encode("utf-8"))
            parent_id = self._fileid_map.lookup_file_id(parent_path)
            if mode_kind(mode) == 'directory':
                root_ie = self._get_dir_ie(from_dir.encode("utf-8"), parent_id)
            else:
                root_ie = self._get_file_ie(from_dir.encode("utf-8"),
                    posixpath.basename(from_dir), mode, hexsha)
        if from_dir != "" or include_root:
            yield (from_dir, "V", root_ie.kind, root_ie.file_id, root_ie)
        todo = set()
        if root_ie.kind == 'directory':
            todo.add((from_dir.encode("utf-8"), hexsha, root_ie.file_id))
        while todo:
            (path, hexsha, parent_id) = todo.pop()
            tree = self.store[hexsha]
            for name, mode, hexsha in tree.iteritems():
                if self.mapping.is_special_file(name):
                    continue
                child_path = posixpath.join(path, name)
                if stat.S_ISDIR(mode):
                    ie = self._get_dir_ie(child_path, parent_id)
                    if recursive:
                        todo.add((child_path, hexsha, ie.file_id))
                else:
                    ie = self._get_file_ie(child_path, name, mode, hexsha, parent_id)
                yield child_path.decode('utf-8'), "V", ie.kind, ie.file_id, ie

    def _get_file_ie(self, path, name, mode, hexsha, parent_id):
        assert isinstance(path, bytes)
        assert isinstance(name, bytes)
        kind = mode_kind(mode)
        file_id = self._fileid_map.lookup_file_id(path)
        ie = inventory.entry_factory[kind](file_id, name.decode("utf-8"), parent_id)
        if kind == 'symlink':
            ie.symlink_target = self.store[hexsha].data.decode('utf-8')
        elif kind == 'tree-reference':
            ie.reference_revision = self.mapping.revision_id_foreign_to_bzr(hexsha)
        else:
            data = self.store[hexsha].data
            ie.text_sha1 = osutils.sha_string(data)
            ie.text_size = len(data)
            ie.executable = mode_is_executable(mode)
        ie.revision = self.get_file_revision(path.decode('utf-8'))
        return ie

    def _get_dir_ie(self, path, parent_id):
        file_id = self._fileid_map.lookup_file_id(path)
        ie = inventory.InventoryDirectory(file_id,
            posixpath.basename(path).decode("utf-8"), parent_id)
        ie.revision = self.get_file_revision(path)
        return ie

    def iter_children(self, file_id):
        path = self._fileid_map.lookup_path(file_id)
        mode, tree_sha = tree_lookup_path(self.store.__getitem__, self.tree, path)
        if stat.S_ISDIR(mode):
            for name, mode, hexsha  in self.store[tree_sha].iteritems():
                yield self._fileid_map.lookup_file_id(posixpath.join(path, name))

    def iter_entries_by_dir(self, specific_file_ids=None, yield_parents=False):
        if self.tree is None:
            return
        if yield_parents:
            # TODO(jelmer): Support yield parents
            raise NotImplementedError
        if specific_file_ids is not None:
            specific_paths = [self.id2path(file_id).encode('utf-8') for file_id in specific_file_ids]
            if specific_paths in ([""], []):
                specific_paths = None
            else:
                specific_paths = set(specific_paths)
        else:
            specific_paths = None
        todo = set([("", self.tree, None)])
        while todo:
            path, tree_sha, parent_id = todo.pop()
            ie = self._get_dir_ie(path, parent_id)
            if specific_paths is None or path in specific_paths:
                yield path.decode("utf-8"), ie
            tree = self.store[tree_sha]
            for name, mode, hexsha  in tree.iteritems():
                if self.mapping.is_special_file(name):
                    continue
                child_path = posixpath.join(path, name)
                if stat.S_ISDIR(mode):
                    if (specific_paths is None or
                        any(filter(lambda p: p.startswith(child_path), specific_paths))):
                        todo.add((child_path, hexsha, ie.file_id))
                elif specific_paths is None or child_path in specific_paths:
                    yield (child_path.decode("utf-8"),
                            self._get_file_ie(child_path, name, mode, hexsha,
                           ie.file_id))

    def get_revision_id(self):
        """See RevisionTree.get_revision_id."""
        return self._revision_id

    def get_file_sha1(self, path, file_id=None, stat_value=None):
        if self.tree is None:
            raise errors.NoSuchFile(path)
        return osutils.sha_string(self.get_file_text(path, file_id))

    def get_file_verifier(self, path, file_id=None, stat_value=None):
        (mode, hexsha) = tree_lookup_path(self.store.__getitem__, self.tree,
            path.encode('utf-8'))
        return ("GIT", hexsha)

    def get_file_text(self, path, file_id=None):
        """See RevisionTree.get_file_text."""
        if self.tree is None:
            raise errors.NoSuchFile(path)
        (mode, hexsha) = tree_lookup_path(self.store.__getitem__, self.tree,
                path.encode('utf-8'))
        if stat.S_ISREG(mode):
            return self.store[hexsha].data
        else:
            return b""

    def get_symlink_target(self, path, file_id=None):
        """See RevisionTree.get_symlink_target."""
        (mode, hexsha) = tree_lookup_path(self.store.__getitem__, self.tree,
                path.encode('utf-8'))
        if stat.S_ISLNK(mode):
            return self.store[hexsha].data.decode('utf-8')
        else:
            return None

    def _comparison_data(self, entry, path):
        if entry is None:
            return None, False, None
        return entry.kind, entry.executable, None

    def path_content_summary(self, path):
        """See Tree.path_content_summary."""
        try:
            (mode, hexsha) = tree_lookup_path(self.store.__getitem__, self.tree, path.encode('utf-8'))
        except KeyError:
            return ('missing', None, None, None)
        kind = mode_kind(mode)
        if kind == 'file':
            executable = mode_is_executable(mode)
            contents = self.store[hexsha].data
            return (kind, len(contents), executable, osutils.sha_string(contents))
        elif kind == 'symlink':
            return (kind, None, None, self.store[hexsha].data)
        else:
            return (kind, None, None, None)


def tree_delta_from_git_changes(changes, mapping,
        (old_fileid_map, new_fileid_map), specific_files=None,
        require_versioned=False, include_root=False):
    """Create a TreeDelta from two git trees.

    source and target are iterators over tuples with:
        (filename, sha, mode)
    """
    ret = delta.TreeDelta()
    for (oldpath, newpath), (oldmode, newmode), (oldsha, newsha) in changes:
        if newpath == u'' and not include_root:
            continue
        if not (specific_files is None or
                (oldpath is not None and osutils.is_inside_or_parent_of_any(specific_files, oldpath)) or
                (newpath is not None and osutils.is_inside_or_parent_of_any(specific_files, newpath))):
            continue
        if mapping.is_special_file(oldpath):
            oldpath = None
        if mapping.is_special_file(newpath):
            newpath = None
        if oldpath is None and newpath is None:
            continue
        if oldpath is None:
            file_id = new_fileid_map.lookup_file_id(newpath)
            ret.added.append((newpath.decode('utf-8'), file_id, mode_kind(newmode)))
        elif newpath is None:
            file_id = old_fileid_map.lookup_file_id(oldpath)
            ret.removed.append((oldpath.decode('utf-8'), file_id, mode_kind(oldmode)))
        elif oldpath != newpath:
            file_id = old_fileid_map.lookup_file_id(oldpath)
            ret.renamed.append(
                (oldpath.decode('utf-8'), newpath.decode('utf-8'), file_id,
                mode_kind(newmode), (oldsha != newsha),
                (oldmode != newmode)))
        elif mode_kind(oldmode) != mode_kind(newmode):
            file_id = new_fileid_map.lookup_file_id(newpath)
            ret.kind_changed.append(
                (newpath.decode('utf-8'), file_id, mode_kind(oldmode),
                mode_kind(newmode)))
        elif oldsha != newsha or oldmode != newmode:
            if stat.S_ISDIR(oldmode) and stat.S_ISDIR(newmode):
                continue
            file_id = new_fileid_map.lookup_file_id(newpath)
            ret.modified.append(
                (newpath.decode('utf-8'), file_id, mode_kind(newmode),
                (oldsha != newsha), (oldmode != newmode)))
        else:
            file_id = new_fileid_map.lookup_file_id(newpath)
            ret.unchanged.append((newpath.decode('utf-8'), file_id, mode_kind(newmode)))
    return ret


def changes_from_git_changes(changes, mapping, specific_files=None, include_unchanged=False):
    """Create a iter_changes-like generator from a git stream.

    source and target are iterators over tuples with:
        (filename, sha, mode)
    """
    for (oldpath, newpath), (oldmode, newmode), (oldsha, newsha) in changes:
        if not (specific_files is None or
                (oldpath is not None and osutils.is_inside_or_parent_of_any(specific_files, oldpath)) or
                (newpath is not None and osutils.is_inside_or_parent_of_any(specific_files, newpath))):
            continue
        path = (oldpath, newpath)
        if oldpath is not None and mapping.is_special_file(oldpath):
            continue
        if newpath is not None and mapping.is_special_file(newpath):
            continue
        if oldpath is None:
            fileid = mapping.generate_file_id(newpath)
            oldexe = None
            oldkind = None
            oldname = None
            oldparent = None
        else:
            oldpath = oldpath.decode("utf-8")
            assert oldmode is not None
            oldexe = mode_is_executable(oldmode)
            oldkind = mode_kind(oldmode)
            if oldpath == u'':
                oldparent = None
                oldname = ''
            else:
                (oldparentpath, oldname) = osutils.split(oldpath)
                oldparent = mapping.generate_file_id(oldparentpath)
            fileid = mapping.generate_file_id(oldpath)
        if newpath is None:
            newexe = None
            newkind = None
            newname = None
            newparent = None
        else:
            newpath = newpath.decode("utf-8")
            if newmode is not None:
                newexe = mode_is_executable(newmode)
                newkind = mode_kind(newmode)
            else:
                newexe = False
                newkind = None
            if newpath == u'':
                newparent = None
                newname = u''
            else:
                newparentpath, newname = osutils.split(newpath)
                newparent = mapping.generate_file_id(newparentpath)
        if (not include_unchanged and
            oldkind == 'directory' and newkind == 'directory' and
            oldpath == newpath):
            continue
        yield (fileid, (oldpath, newpath), (oldsha != newsha),
             (oldpath is not None, newpath is not None),
             (oldparent, newparent), (oldname, newname),
             (oldkind, newkind), (oldexe, newexe))


class InterGitTrees(tree.InterTree):
    """InterTree that works between two git trees."""

    _matching_from_tree_format = None
    _matching_to_tree_format = None
    _test_mutable_trees_to_test_trees = None

    @classmethod
    def is_compatible(cls, source, target):
        return (isinstance(source, GitRevisionTree) and
                isinstance(target, GitRevisionTree))

    def compare(self, want_unchanged=False, specific_files=None,
                extra_trees=None, require_versioned=False, include_root=False,
                want_unversioned=False):
        changes = self._iter_git_changes(want_unchanged=want_unchanged,
                require_versioned=require_versioned,
                specific_files=specific_files)
        source_fileid_map = self.source._fileid_map
        target_fileid_map = self.target._fileid_map
        return tree_delta_from_git_changes(changes, self.target.mapping,
            (source_fileid_map, target_fileid_map),
            specific_files=specific_files, include_root=include_root)

    def iter_changes(self, include_unchanged=False, specific_files=None,
                     pb=None, extra_trees=[], require_versioned=True,
                     want_unversioned=False):
        changes = self._iter_git_changes(want_unchanged=include_unchanged,
                require_versioned=require_versioned,
                specific_files=specific_files)
        return changes_from_git_changes(changes, self.target.mapping,
            specific_files=specific_files, include_unchanged=include_unchanged)

    def _iter_git_changes(self, want_unchanged=False):
        raise NotImplementedError(self._iter_git_changes)


class InterGitRevisionTrees(InterGitTrees):
    """InterTree that works between two git revision trees."""

    _matching_from_tree_format = None
    _matching_to_tree_format = None
    _test_mutable_trees_to_test_trees = None

    @classmethod
    def is_compatible(cls, source, target):
        return (isinstance(source, GitRevisionTree) and
                isinstance(target, GitRevisionTree))

    def _iter_git_changes(self, want_unchanged=False, require_versioned=False,
            specific_files=None):
        if require_versioned and specific_files:
            for path in specific_files:
                if (not self.source.is_versioned(path) and
                    not self.target.is_versioned(path)):
                    raise errors.PathsNotVersionedError(path)

        if self.source._repository._git.object_store != self.target._repository._git.object_store:
            store = OverlayObjectStore([self.source._repository._git.object_store,
                                        self.target._repository._git.object_store])
        else:
            store = self.source._repository._git.object_store
        return self.source._repository._git.object_store.tree_changes(
            self.source.tree, self.target.tree, want_unchanged=want_unchanged,
            include_trees=True, change_type_same=True)


tree.InterTree.register_optimiser(InterGitRevisionTrees)
