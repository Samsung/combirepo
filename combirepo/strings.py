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

import re
import logging
import urlparse


def split_names_list(names):
    """
    Splits the given list of names to the list of names, as follows:

    gcc,bash m4
    flex;bison,yacc

    to python list ["gcc", "bash", "m4", "flex", "bison", "yacc"]

    @param names    The list of names

    @return         The splitted list of names
    """
    if names is None:
        return None
    splitted_names = []
    for name in names:
        for splitted_name in re.split("[\,\;\ \n\t]", name):
            if len(splitted_name) > 0:
                splitted_names.append(splitted_name)

    logging.debug("Resulting list after splitting: {0}".format(splitted_names))
    return splitted_names


def split_names(names):
    """
    Splits the names string as the previsou function.

    @param names    The string that contains strings.
    @return         The list of names.
    """
    splitted_names = split_names_list([names])
    return splitted_names


def is_valid_identifier(string):
    """
    Checks whether the given string is a valid identifier.

    @param string   The string to be checked.
    @return         True, if it is a valid identifier, false otherwise.
    """
    identifier = re.compile(r"^[^\d\W]\w*\Z")
    return re.match(identifier, string) is not None


def is_ascii_string(string):
    """
    Checks whether the given string is an ASCII string.

    @param string   The string to be checked.
    @return         True, if it is a valid ASCII string, false otherwise.
    """
    try:
        string.decode('ascii')
    except UnicodeDecodeError:
        return False
    else:
        return True


def is_url_string(string):
    """
    Checks whether the given string is a URL string.

    @param string   The string to be checked.
    @return         True, if it is a valid URL string, false otherwise.
    """
    url_parsed = urlparse.urlparse(string)
    if url_parsed is None:
        return False
    else:
        return bool(url_parsed.scheme)
