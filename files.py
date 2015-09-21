#!/usr/bin/env python2.7
# -*- coding: utf-8 -*-
import os
import sys
import logging
import re
import check


def find_fast(directory, expression):
    """
    Finds all files in the given directory that match the given expression.

    @param directory    The directory.
    @param expressiion  The regular expression.
    """
    logging.debug("Searching expression {0} in directory "
                  "{1}".format(expression, directory))
    check.directory_exists(directory)

    matcher = re.compile(expression)
    files_found = []
    for root, dirs, files in os.walk(directory):
        for file_name in files:
            if matcher.match(file_name):
                path = os.path.join(root, file_name)
                path = os.path.abspath(path)
                files_found.append(path)

    return files_found


def create_symlink(package_name, location_from, directory_to):
    """
    Creates symlink from file to the file with the same name in the another
    directory.

    @param package          The name of package
    @param location_from    Source of the symlink
    @param directory_to     Destination directory of the symlink
    """
    check.file_exists(location_from)

    location_to = os.path.join(directory_to,
                               os.path.basename(location_from))

    logging.debug("Creating symlink from {0} to {1}".format(location_from,
                                                            location_to))
    os.symlink(location_from, location_to)
