#!/usr/bin/env python2.7
# -*- coding: utf-8 -*-
import tempfile
import atexit
import shutil
import os
import logging

debug_mode = False

# FIXME: Rename default names of temporary files and directories when the
# default name of our utility will be chosen. Now they all have prefix
# "combi-repo". Also it should be better to have some "macro" for it.


def create_temporary_file(file_suffix):
    """
    Creates temporary file in tmpfs, named as follows:

    /tmp/combi-repo.<random>.<suffix>

    @param file_suffix      The suffix of temporary file.

    @return                 The path to created temporary file.
    """
    file_descriptor, path = tempfile.mkstemp(prefix='combi-repo.',
                                             suffix="." + file_suffix)
    os.close(file_descriptor)  # This helps to avoid the file descriptor leak.
    if not debug_mode:
        atexit.register(os.remove, path)  # It will be removed at exit.
    logging.debug("Created temporary file {0}".format(path))
    return path


# FIXME: Ditto.
def create_temporary_directory(directory_suffix):
    """
    Creates temporary directory in tmpfs, named as follows:

    /tmp/combi-repo.<random>.<suffix>

    @param file_suffix      The suffix of temporary directory.

    @return                 The path to created temporary directory.
    """
    path = tempfile.mkdtemp(prefix='combi-repo.',
                            suffix="." + directory_suffix)
    if not debug_mode:
        atexit.register(shutil.rmtree, path)  # It will be removed at exit.
    logging.debug("Created temporary file {0}".format(path))
    return path
