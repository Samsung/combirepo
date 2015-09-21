#!/usr/bin/env python2.7
# -*- coding: utf-8 -*-
import sys
import subprocess
import tempfile
import atexit
import shutil
import os
import logging

debug_mode = False
default_directory = None


def create_temporary_file(file_suffix):
    """
    Creates temporary file in tmpfs, named as follows:

    default_directory/combirepo.<random>.<suffix>

    @param file_suffix      The suffix of temporary file.

    @return                 The path to created temporary file.
    """
    global default_directory
    if not os.path.isdir(default_directory):
        os.makedirs(default_directory)
    file_descriptor, path = tempfile.mkstemp(prefix='combirepo.',
                                             suffix="." + file_suffix,
                                             dir=default_directory)
    os.close(file_descriptor)  # This helps to avoid the file descriptor leak.
    if not debug_mode:
        atexit.register(os.remove, path)  # It will be removed at exit.
    logging.debug("Created temporary file {0}".format(path))
    return path


def create_temporary_directory(directory_suffix):
    """
    Creates temporary directory in tmpfs, named as follows:

    default_directory/combirepo.<random>.<suffix>

    @param file_suffix      The suffix of temporary directory.

    @return                 The path to created temporary directory.
    """
    global default_directory
    if not os.path.isdir(default_directory):
        os.makedirs(default_directory)
    path = tempfile.mkdtemp(prefix='combirepo.',
                            suffix="." + directory_suffix,
                            dir=default_directory)
    if not debug_mode:
        atexit.register(shutil.rmtree, path)  # It will be removed at exit.
    logging.debug("Created temporary file {0}".format(path))
    return path


def mount_image(directory, image_path):
    """
    Creates temporary mount point of the given image in the given directory.

    default_directory/combirepo.<random>.<suffix>

    and mounts the image to it.

    @param directory        The path to the directory.
    @param image_path       The path to the image to be mounted.

    @return                 The path to created temporary directory.
    """
    value = subprocess.call(["mount", "-o", "rw,loop", image_path, directory])
    if value != 0:
        logging.error("Failed to mount image.")
        sys.exit("Error.")
    if not debug_mode:
        atexit.register(subprocess.call, ["umount", "-l", directory])
    logging.debug("Mounted image {0} to {1}".format(image_path, directory))
    return
