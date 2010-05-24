# Copyright (C) 2005, 2006, 2008, 2009, 2010 Canonical Ltd
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

"""Export a Tree to a non-versioned directory.
"""

import StringIO
import sys
import tarfile
import time

from bzrlib import export, osutils
from bzrlib.export import _export_iter_entries
from bzrlib.filters import (
    ContentFilterContext,
    filtered_output_bytes,
    )
from bzrlib.trace import mutter


def tar_exporter(tree, dest, root, subdir, compression=None, filtered=False,
                 per_file_timestamps=False):
    """Export this tree to a new tar file.

    `dest` will be created holding the contents of this tree; if it
    already exists, it will be clobbered, like with "tar -c".
    """
    mutter('export version %r', tree)
    now = time.time()
    compression = str(compression or '')
    if dest == '-':
        # XXX: If no root is given, the output tarball will contain files
        # named '-/foo'; perhaps this is the most reasonable thing.
        ball = tarfile.open(None, 'w|' + compression, sys.stdout)
    else:
        if root is None:
            root = export.get_root_name(dest)

        # tarfile.open goes on to do 'os.getcwd() + dest' for opening
        # the tar file. With dest being unicode, this throws UnicodeDecodeError
        # unless we encode dest before passing it on. This works around
        # upstream python bug http://bugs.python.org/issue8396
        # (fixed in Python 2.6.5 and 2.7b1)
        ball = tarfile.open(dest.encode(osutils._fs_enc), 'w:' + compression)

    for dp, ie in _export_iter_entries(tree, subdir):
        filename = osutils.pathjoin(root, dp).encode('utf8')
        item = tarfile.TarInfo(filename)
        if per_file_timestamps:
            item.mtime = tree.get_file_mtime(ie.file_id, dp)
        else:
            item.mtime = now
        if ie.kind == "file":
            item.type = tarfile.REGTYPE
            if tree.is_executable(ie.file_id):
                item.mode = 0755
            else:
                item.mode = 0644
            if filtered:
                chunks = tree.get_file_lines(ie.file_id)
                filters = tree._content_filter_stack(dp)
                context = ContentFilterContext(dp, tree, ie)
                contents = filtered_output_bytes(chunks, filters, context)
                content = ''.join(contents)
                item.size = len(content)
                fileobj = StringIO.StringIO(content)
            else:
                item.size = ie.text_size
                fileobj = tree.get_file(ie.file_id)
        elif ie.kind == "directory":
            item.type = tarfile.DIRTYPE
            item.name += '/'
            item.size = 0
            item.mode = 0755
            fileobj = None
        elif ie.kind == "symlink":
            item.type = tarfile.SYMTYPE
            item.size = 0
            item.mode = 0755
            item.linkname = ie.symlink_target
            fileobj = None
        else:
            raise BzrError("don't know how to export {%s} of kind %r" %
                           (ie.file_id, ie.kind))
        ball.addfile(item, fileobj)
    ball.close()


def tgz_exporter(tree, dest, root, subdir, filtered=False,
                 per_file_timestamps=False):
    tar_exporter(tree, dest, root, subdir, compression='gz',
                 filtered=filtered, per_file_timestamps=per_file_timestamps)


def tbz_exporter(tree, dest, root, subdir, filtered=False,
                 per_file_timestamps=False):
    tar_exporter(tree, dest, root, subdir, compression='bz2',
                 filtered=filtered, per_file_timestamps=per_file_timestamps)