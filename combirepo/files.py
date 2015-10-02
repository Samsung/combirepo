#!/usr/bin/env python2.7
# -*- coding: utf-8 -*-
import os
import shutil
import sys
import logging
import re
import check
import hidden_subprocess


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


def unrpm(rpm_path, destination_path):
    """
    Unpacks the RPM package from the given location to the given directory.

    @param rpm_path             The path to the RPM file.
    @param destination_path     The path to the destination directory.
    """
    check.file_exists(rpm_path)
    check.directory_exists(destination_path)
    if not rpm_path.endswith(".rpm"):
        logging.error("Given file {0} is not an RPM package!".format(rpm_path))
    initial_directory = os.getcwd()
    os.chdir(destination_path)
    hidden_subprocess.silent_pipe_call(["rpm2cpio", rpm_path],
                                       ["cpio", "--extract", "--unconditional",
                                        "--preserve-modification-time",
                                        "--make-directories"])
    os.chdir(initial_directory)


def safe_rmtree(path):
    """
    Removes the directory safely, i. e. does not raise exception in case when
    the directory does not exit.

    @param path     The path to the directory.
    """
    if os.path.isdir(path):
        shutil.rmtree(path)
