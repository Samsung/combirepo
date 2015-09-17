#!/usr/bin/env python2.7
# -*- coding: utf-8 -*-
import re
import logging


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
