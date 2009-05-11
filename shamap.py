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

"""Map from Git sha's to Bazaar objects."""

import os
import threading

import bzrlib
from bzrlib.errors import (
    NoSuchRevision,
    )


def check_pysqlite_version(sqlite3):
    """Check that sqlite library is compatible.

    """
    if (sqlite3.sqlite_version_info[0] < 3 or 
            (sqlite3.sqlite_version_info[0] == 3 and 
             sqlite3.sqlite_version_info[1] < 3)):
        warning('Needs at least sqlite 3.3.x')
        raise bzrlib.errors.BzrError("incompatible sqlite library")

try:
    try:
        import sqlite3
        check_pysqlite_version(sqlite3)
    except (ImportError, bzrlib.errors.BzrError), e: 
        from pysqlite2 import dbapi2 as sqlite3
        check_pysqlite_version(sqlite3)
except:
    warning('Needs at least Python2.5 or Python2.4 with the pysqlite2 '
            'module')
    raise bzrlib.errors.BzrError("missing sqlite library")


_mapdbs = threading.local()
def mapdbs():
    """Get a cache for this thread's db connections."""
    try:
        return _mapdbs.cache
    except AttributeError:
        _mapdbs.cache = {}
        return _mapdbs.cache


class GitShaMap(object):
    """Git<->Bzr revision id mapping database."""

    def add_entry(self, sha, type, type_data):
        """Add a new entry to the database.
        """
        raise NotImplementedError(self.add_entry)

    def add_entries(self, entries):
        """Add multiple new entries to the database.
        """
        for e in entries:
            self.add_entry(*e)

    def lookup_tree(self, fileid, revid):
        """Lookup the SHA of a git tree."""
        raise NotImplementedError(self.lookup_tree)

    def lookup_blob(self, fileid, revid):
        """Lookup a blob by the fileid it has in a bzr revision."""
        raise NotImplementedError(self.lookup_blob)

    def lookup_git_sha(self, sha):
        """Lookup a Git sha in the database.

        :param sha: Git object sha
        :return: (type, type_data) with type_data:
            revision: revid, tree sha
        """
        raise NotImplementedError(self.lookup_git_sha)

    def revids(self):
        """List the revision ids known."""
        raise NotImplementedError(self.revids)

    def sha1s(Self):
        """List the SHA1s."""
        raise NotImplementedError(self.sha1s)

    def commit(self):
        """Commit any pending changes."""


class DictGitShaMap(GitShaMap):

    def __init__(self):
        self.dict = {}

    def add_entry(self, sha, type, type_data):
        self.dict[sha] = (type, type_data)

    def lookup_git_sha(self, sha):
        return self.dict[sha]

    def lookup_tree(self, fileid, revid):
        for k, v in self.dict.iteritems():
            if v == ("tree", (fileid, revid)):
                return k
        raise KeyError((fileid, revid))

    def lookup_blob(self, fileid, revid):
        for k, v in self.dict.iteritems():
            if v == ("blob", (fileid, revid)):
                return k
        raise KeyError((fileid, revid))

    def revids(self):
        for key, (type, type_data) in self.dict.iteritems():
            if type == "commit":
                yield type_data[0]

    def sha1s(self):
        return self.dict.iterkeys()


class SqliteGitShaMap(GitShaMap):

    def __init__(self, path=None):
        self.path = path
        if path is None:
            self.db = sqlite3.connect(":memory:")
        else:
            if not mapdbs().has_key(path):
                mapdbs()[path] = sqlite3.connect(path)
            self.db = mapdbs()[path]    
        self.db.executescript("""
        create table if not exists commits(sha1 text, revid text, tree_sha text);
        create index if not exists commit_sha1 on commits(sha1);
        create unique index if not exists commit_revid on commits(revid);
        create table if not exists blobs(sha1 text, fileid text, revid text);
        create index if not exists blobs_sha1 on blobs(sha1);
        create unique index if not exists blobs_fileid_revid on blobs(fileid, revid);
        create table if not exists trees(sha1 text, fileid text, revid text);
        create index if not exists trees_sha1 on trees(sha1);
        create unique index if not exists trees_fileid_revid on trees(fileid, revid);
""")

    @classmethod
    def from_repository(cls, repository):
        return cls(os.path.join(repository._transport.local_abspath("."), "git.db"))

    def _parent_lookup(self, revid):
        row = self.db.execute("select sha1 from commits where revid = ?", (revid,)).fetchone()
        if row is not None:
            return row[0].encode("utf-8")
        raise KeyError

    def commit(self):
        self.db.commit()

    def add_entries(self, entries):
        trees = []
        blobs = []
        for sha, type, type_data in entries:
            assert isinstance(type_data[0], str)
            assert isinstance(type_data[1], str)
            entry = (sha.decode("utf-8"), type_data[0].decode("utf-8"), 
                     type_data[1].decode("utf-8"))
            if type == "tree":
                trees.append(entry)
            elif type == "blob":
                blobs.append(entry)
            else:
                raise AssertionError
        if trees:
            self.db.executemany("replace into trees (sha1, fileid, revid) values (?, ?, ?)", trees)
        if blobs:
            self.db.executemany("replace into blobs (sha1, fileid, revid) values (?, ?, ?)", blobs)


    def add_entry(self, sha, type, type_data):
        """Add a new entry to the database.
        """
        assert isinstance(type_data, tuple)
        assert isinstance(sha, str), "type was %r" % sha
        if type == "commit":
            self.db.execute("replace into commits (sha1, revid, tree_sha) values (?, ?, ?)", (sha, type_data[0], type_data[1]))
        elif type in ("blob", "tree"):
            self.db.execute("replace into %ss (sha1, fileid, revid) values (?, ?, ?)" % type, (sha, type_data[0], type_data[1]))
        else:
            raise AssertionError("Unknown type %s" % type)

    def lookup_tree(self, fileid, revid):
        row = self.db.execute("select sha1 from trees where fileid = ? and revid = ?", (fileid,revid)).fetchone()
        if row is None:
            raise KeyError((fileid, revid))
        return row[0].encode("utf-8")

    def lookup_blob(self, fileid, revid):
        row = self.db.execute("select sha1 from blobs where fileid = ? and revid = ?", (fileid, revid)).fetchone()
        if row is None:
            raise KeyError((fileid, revid))
        return row[0].encode("utf-8")

    def lookup_git_sha(self, sha):
        """Lookup a Git sha in the database.

        :param sha: Git object sha
        :return: (type, type_data) with type_data:
            revision: revid, tree sha
        """
        def format(type, row):
            return (type, (row[0].encode("utf-8"), row[1].encode("utf-8")))
        row = self.db.execute("select revid, tree_sha from commits where sha1 = ?", (sha,)).fetchone()
        if row is not None:
            return format("commit", row)
        row = self.db.execute("select fileid, revid from blobs where sha1 = ?", (sha,)).fetchone()
        if row is not None:
            return format("blob", row)
        row = self.db.execute("select fileid, revid from trees where sha1 = ?", (sha,)).fetchone()
        if row is not None:
            return format("tree", row)
        raise KeyError(sha)

    def revids(self):
        """List the revision ids known."""
        for row in self.db.execute("select revid from commits").fetchall():
            yield row[0].encode("utf-8")

    def sha1s(self):
        """List the SHA1s."""
        for table in ("blobs", "commits", "trees"):
            for row in self.db.execute("select sha1 from %s" % table).fetchall():
                yield row[0].encode("utf-8")


TDB_MAP_VERSION = 1


class TdbGitShaMap(GitShaMap):
    """SHA Map that uses a TDB database.

    Entries:

    "git <sha1>" -> "<type> <type-data1> <type-data2>"
    "commit revid" -> "<sha1> <tree-id>"
    "tree fileid revid" -> "<sha1>"
    "blob fileid revid" -> "<sha1>"
    """

    def __init__(self, path=None):
        import tdb
        self.path = path
        if path is None:
            self.db = {}
        else:
            if not mapdbs().has_key(path):
                mapdbs()[path] = tdb.open(path, 0, tdb.DEFAULT, 
                                          os.O_RDWR|os.O_CREAT)
            self.db = mapdbs()[path]    
        if not "version" in self.db:
            self.db["version"] = str(TDB_MAP_VERSION)
        else:
            assert int(self.db["version"]) == TDB_MAP_VERSION

    @classmethod
    def from_repository(cls, repository):
        try:
            return cls(os.path.join(repository._transport.local_abspath("."), "git.tdb"))
        except bzrlib.errors.NotLocalUrl:
            from bzrlib.config import config_dir
            return cls(os.path.join(config_dir(), "remote-git.tdb"))

    def _parent_lookup(self, revid):
        return self.db["commit %s" % revid].split(" ")[0]

    def commit(self):
        pass

    def add_entry(self, sha, type, type_data):
        """Add a new entry to the database.
        """
        self.db["git %s" % sha] = "%s %s %s" % (type, type_data[0], type_data[1])
        if type == "commit":
            self.db["commit %s" % type_data[0]] = "%s %s" % (sha, type_data[1])
        else:
            self.db["%s %s %s" % (type, type_data[0], type_data[1])] = sha

    def lookup_tree(self, fileid, revid):
        return self.db["tree %s %s" % (fileid, revid)]

    def lookup_blob(self, fileid, revid):
        return self.db["blob %s %s" % (fileid, revid)]

    def lookup_git_sha(self, sha):
        """Lookup a Git sha in the database.

        :param sha: Git object sha
        :return: (type, type_data) with type_data:
            revision: revid, tree sha
        """
        data = self.db["git %s" % sha].split(" ")
        return (data[0], (data[1], data[2]))

    def revids(self):
        """List the revision ids known."""
        for key in self.db.iterkeys():
            if key.startswith("commit "):
                yield key.split(" ")[1]

    def sha1s(self):
        """List the SHA1s."""
        for key in self.db.iterkeys():
            if key.startswith("git "):
                yield key.split(" ")[1]
