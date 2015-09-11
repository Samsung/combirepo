#!/usr/bin/env python2.7
# -*- coding: utf-8 -*-
import os
import sys
import errno
import subprocess
import logging


def command_exists(command):
    """
    Checks whether the command exists in the given PATH evironment and exits
    the program in the case of failure.

    @param command  The command.
    @return         True if command exists,
                    False if file exists but is not executable,
                    exits otherwise.
    """
    logging.debug("Checking command \"{0}\"".format(command))
    try:
        DEV_NULL = open(os.devnull, 'w')
        subprocess.call([command], stdout=DEV_NULL, stderr=DEV_NULL)
    except OSError as error:
        if os.path.isfile(command):
            logging.error("File {0} cannot be executed.".format(command))
            return False
        elif error.errno == errno.ENOENT:
            logging.error("\"{0}\" command is not available. Try to "
                          "install it!".format(command))
        else:
            logging.error("Unknown error happened during checking the "
                          "command \"{0}\"!".format(command))
        sys.exit("Error.")
    return True
