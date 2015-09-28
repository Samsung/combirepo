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


def pipe_call(commandline_from, commandline_to):
    """
    Calls two commands redirecting the output of first command to the second
    one.

    @param commandline_from     The first command.
    @param commandline_to       The second command.
    """
    code = 0
    global counter
    counter = 1
    logging.info("Running the command: {0} | "
                 "{1}".format(" ".join(commandline_from),
                              " ".join(commandline_to)))
    logging.debug("       in the directory {0}".format(os.getcwd()))
    log_file_name = temporaries.create_temporary_file("process.log")

    timer = RepeatingTimer(1.0, progress_bar_print)
    timer.daemon = True
    timer.start()

    global visible_mode
    first = subprocess.Popen(commandline_from, stdout=subprocess.PIPE)
    second = subprocess.Popen(commandline_to, stdin=first.stdout,
                              stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE)
    # Allow first to receive a SIGPIPE if second exits:
    first.stdout.close()
    output, errors = second.communicate()
    with open(log_file_name, 'w') as log_file:
        log_file.write(output)
        log_file.write(errors)

    timer.cancel()
    sys.stdout.write("\n")
