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
            splitted_names.append(splitted_name)

    logging.debug("Resulting list after splitting: {0}".format(splitted_names))
    return splitted_names
