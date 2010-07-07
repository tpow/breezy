# Copyright (C) 2007-2010 Canonical Ltd
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

"""Tag strategies.

These are contained within a branch and normally constructed
when the branch is opened.  Clients should typically do

  Branch.tags.add('name', 'value')
"""

# NOTE: I was going to call this tags.py, but vim seems to think all files
# called tags* are ctags files... mbp 20070220.


from bzrlib import (
    bencode,
    errors,
    trace,
    )


class _Tags(object):

    def __init__(self, branch):
        self.branch = branch

    def has_tag(self, tag_name):
        return self.get_tag_dict().has_key(tag_name)


class DisabledTags(_Tags):
    """Tag storage that refuses to store anything.

    This is used by older formats that can't store tags.
    """

    def _not_supported(self, *a, **k):
        raise errors.TagsNotSupported(self.branch)

    set_tag = _not_supported
    get_tag_dict = _not_supported
    _set_tag_dict = _not_supported
    lookup_tag = _not_supported
    delete_tag = _not_supported

    def merge_to(self, to_tags, overwrite=False):
        # we never have anything to copy
        pass

    def rename_revisions(self, rename_map):
        # No tags, so nothing to rename
        pass

    def get_reverse_tag_dict(self):
        # There aren't any tags, so the reverse mapping is empty.
        return {}


class BasicTags(_Tags):
    """Tag storage in an unversioned branch control file.
    """

    def set_tag(self, tag_name, tag_target):
        """Add a tag definition to the branch.

        Behaviour if the tag is already present is not defined (yet).
        """
        # all done with a write lock held, so this looks atomic
        self.branch.lock_write()
        try:
            master = self.branch.get_master_branch()
            if master is not None:
                master.tags.set_tag(tag_name, tag_target)
            td = self.get_tag_dict()
            td[tag_name] = tag_target
            self._set_tag_dict(td)
        finally:
            self.branch.unlock()

    def lookup_tag(self, tag_name):
        """Return the referent string of a tag"""
        td = self.get_tag_dict()
        try:
            return td[tag_name]
        except KeyError:
            raise errors.NoSuchTag(tag_name)

    def get_tag_dict(self):
        self.branch.lock_read()
        try:
            try:
                tag_content = self.branch._get_tags_bytes()
            except errors.NoSuchFile, e:
                # ugly, but only abentley should see this :)
                trace.warning('No branch/tags file in %s.  '
                     'This branch was probably created by bzr 0.15pre.  '
                     'Create an empty file to silence this message.'
                     % (self.branch, ))
                return {}
            return self._deserialize_tag_dict(tag_content)
        finally:
            self.branch.unlock()

    def get_reverse_tag_dict(self):
        """Returns a dict with revisions as keys
           and a list of tags for that revision as value"""
        d = self.get_tag_dict()
        rev = {}
        for key in d:
            try:
                rev[d[key]].append(key)
            except KeyError:
                rev[d[key]] = [key]
        return rev

    def delete_tag(self, tag_name):
        """Delete a tag definition.
        """
        self.branch.lock_write()
        try:
            d = self.get_tag_dict()
            try:
                del d[tag_name]
            except KeyError:
                raise errors.NoSuchTag(tag_name)
            master = self.branch.get_master_branch()
            if master is not None:
                try:
                    master.tags.delete_tag(tag_name)
                except errors.NoSuchTag:
                    pass
            self._set_tag_dict(d)
        finally:
            self.branch.unlock()

    def _set_tag_dict(self, new_dict):
        """Replace all tag definitions

        WARNING: Calling this on an unlocked branch will lock it, and will
        replace the tags without warning on conflicts.

        :param new_dict: Dictionary from tag name to target.
        """
        return self.branch._set_tags_bytes(self._serialize_tag_dict(new_dict))

    def _serialize_tag_dict(self, tag_dict):
        td = dict((k.encode('utf-8'), v)
                  for k,v in tag_dict.items())
        return bencode.bencode(td)

    def _deserialize_tag_dict(self, tag_content):
        """Convert the tag file into a dictionary of tags"""
        # was a special case to make initialization easy, an empty definition
        # is an empty dictionary
        if tag_content == '':
            return {}
        try:
            r = {}
            for k, v in bencode.bdecode(tag_content).items():
                r[k.decode('utf-8')] = v
            return r
        except ValueError, e:
            raise ValueError("failed to deserialize tag dictionary %r: %s"
                % (tag_content, e))

    def merge_to(self, to_tags, overwrite=False):
        """Copy tags between repositories if necessary and possible.

        This method has common command-line behaviour about handling
        error cases.

        All new definitions are copied across, except that tags that already
        exist keep their existing definitions.

        :param to_tags: Branch to receive these tags
        :param overwrite: Overwrite conflicting tags in the target branch

        :returns: A list of tags that conflicted, each of which is
            (tagname, source_target, dest_target), or None if no copying was
            done.
        """
        if self.branch == to_tags.branch:
            return
        if not self.branch.supports_tags():
            # obviously nothing to copy
            return
        source_dict = self.get_tag_dict()
        if not source_dict:
            # no tags in the source, and we don't want to clobber anything
            # that's in the destination
            return
        to_tags.branch.lock_write()
        try:
            dest_dict = to_tags.get_tag_dict()
            result, conflicts = self._reconcile_tags(source_dict, dest_dict,
                                                     overwrite)
            if result != dest_dict:
                to_tags._set_tag_dict(result)
        finally:
            to_tags.branch.unlock()
        return conflicts

    def rename_revisions(self, rename_map):
        """Rename revisions in this tags dictionary.
        
        :param rename_map: Dictionary mapping old revids to new revids
        """
        reverse_tags = self.get_reverse_tag_dict()
        for revid, names in reverse_tags.iteritems():
            if revid in rename_map:
                for name in names:
                    self.set_tag(name, rename_map[revid])

    def _reconcile_tags(self, source_dict, dest_dict, overwrite):
        """Do a two-way merge of two tag dictionaries.

        only in source => source value
        only in destination => destination value
        same definitions => that
        different definitions => if overwrite is False, keep destination
            value and give a warning, otherwise use the source value

        :returns: (result_dict,
            [(conflicting_tag, source_target, dest_target)])
        """
        conflicts = []
        result = dict(dest_dict) # copy
        for name, target in source_dict.items():
            if name not in result or overwrite:
                result[name] = target
            elif result[name] == target:
                pass
            else:
                conflicts.append((name, target, result[name]))
        return result, conflicts


def _merge_tags_if_possible(from_branch, to_branch):
    from_branch.tags.merge_to(to_branch.tags)
