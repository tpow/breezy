# Copyright (C) 2012 Jelmer Vernooij <jelmer@samba.org>

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


"""Directory service for gitorious."""

from __future__ import absolute_import

from __future__ import absolute_import
from bzrlib import transport

transport.register_urlparse_netloc_protocol('github')

class GitHubDirectory(object):

    def look_up(self, name, url):
        """See DirectoryService.look_up"""
        return "git+ssh://git@github.com/" + name