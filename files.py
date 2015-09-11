#!/usr/bin/env python2.7
# -*- coding: utf-8 -*-
import os
import logging
import re


def find_fast(directory, expression):
    """
    Finds all files in the given directory that match the given expression.

    @param directory    The directory.
    @param expressiion  The regular expression.
    """
    logging.debug("Searching expression {0} in directory "
                  "{1}".format(expression, directory))
    if not os.path.isdir(directory):
        raise Exception("Directory {0} does not exist!".format(directory))

    matcher = re.compile(expression)
    files_found = []
    for root, dirs, files in os.walk(directory):
        for file_name in files:
            if matcher.match(file_name):
                path = os.path.join(root, file_name)
                path = os.path.abspath(path)
                files_found.append(path)

    return files_found
