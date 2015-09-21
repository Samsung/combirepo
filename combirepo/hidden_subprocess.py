#!/usr/bin/env python2.7
# -*- coding: utf-8 -*-
import os
import sys
import subprocess
import threading
import logging
import temporaries


visible_mode = False


class RepeatingTimer(threading._Timer):
    """
    Simple timer.
    """
    def run(self):
        """
        Calls the specified function with which it was initialized.
        """
        while True:
            self.finished.wait(self.interval)
            if self.finished.is_set():
                return
            else:
                self.function(*self.args, **self.kwargs)


counter = 1


def progress_bar_print():
    """
    Prints the simple progress bar to the stdout.
    """
    sys.stdout.write("\r")
    global counter
    for i in range(counter):
        sys.stdout.write("#")
    sys.stdout.flush()
    counter = counter + 1


def call(commandline):
    """
    Calls the subprocess and hides all its output.

    @param commandline  The list of command-line words to be executed.

    @return             The return code of the process
    """
    code = 0
    global counter
    counter = 1
    logging.info("Running the command: {0}".format(" ".join(commandline)))
    logging.debug("       in the directory {0}".format(os.getcwd()))

    global visible_mode
    if visible_mode:
        code = subprocess.call(commandline)
    else:
        log_file_name = temporaries.create_temporary_file("process.log")

        timer = RepeatingTimer(1.0, progress_bar_print)
        timer.daemon = True
        timer.start()

        with open(log_file_name, 'w') as log_file:
            code = subprocess.call(commandline, stdout=log_file,
                                   stderr=log_file)
        timer.cancel()
        sys.stdout.write("\n")

        if code != 0:
            logging.error("The subprocess failed!")
            logging.error("STDERR output:")
            with open(log_file_name, 'r') as log_file:
                logging.error("{0}".format(log_file.read()))

    return code
