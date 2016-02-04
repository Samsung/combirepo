#!/usr/bin/env python2.7
# -*- coding: utf-8 -*-
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
# Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA 02111-1307, USA.
#
# Copyright (C) Samsung Electronics, 2016
#
# 2016         Ilya Palachev                 <i.palachev@samsung.com>

import os
import strings
import check


class RepositoryPair(object):
    """
    The pair of repositories (original and marked) that should be combined in
    the future.
    """
    def __init__(self):
        """
        Initializes the repository pair (does nothing).
        """
        self._alias = None
        self._name = None
        self._url = None
        self._url_marked = None

    @property
    def alias(self):
        """The alias of the repository pair (simple name)."""
        return self._alias

    @alias.setter
    def alias(self, value):
        check.valid_identifier(value)
        self._alias = value

    @alias.deleter
    def alias(self):
        del self._alias

    @property
    def name(self):
        """
        The name of the repository as it is mentioned in the kickstart file.
        """
        return self._name

    @name.setter
    def name(self, value):
        check.valid_ascii_string(value)
        self._name = value

    @name.deleter
    def name(self):
        del self._name

    @property
    def url(self):
        """The URL of the original repository."""
        return self._url

    @url.setter
    def url(self, value):
        if os.path.isdir(value):
            self._url = os.path.abspath(value)
        else:
            check.valid_url_string(value)
            self._url = value

    @url.deleter
    def url(self):
        del self.url

    @property
    def url_marked(self):
        """The URL of the marked repository."""
        return self._url_marked

    @url_marked.setter
    def url_marked(self, value):
        if os.path.isdir(value):
            self._url_marked = os.path.abspath(value)
        else:
            check.valid_url_string(value)
            self._url_marked = value

    @url_marked.deleter
    def url_marked(self):
        del self._url_marked
