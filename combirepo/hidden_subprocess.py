#!/usr/bin/env python2.7
# -*- coding: utf-8 -*-
import os
import sys
import subprocess
import multiprocessing
import multiprocessing.pool
import threading
import logging
import time
import temporaries


visible_mode = False
latency = 0.3


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
bar_comment = ""


def progress_bar_print():
    """
    Prints the simple progress bar to the stdout.
    """
    progress_symbols = ['|', '/', '—', '\\']
    sys.stdout.write("\r")
    global counter
    progress_symbol = progress_symbols[counter % len(progress_symbols)]
    progress = "[ " + progress_symbol + " ]"
    progress_bar = bar_comment + " " + progress
    sys.stdout.write(progress_bar)
    sys.stdout.flush()
    counter = counter + 1


def call(comment, commandline):
    """
    Calls the subprocess and hides all its output.

    @param comment      The comment that the user will see.
    @param commandline  The list of command-line words to be executed.

    @return             The return code of the process
    """
    code = 0
    global counter
    counter = 1
    global bar_comment
    bar_comment = comment
    logging.debug("Running the command: {0}".format(" ".join(commandline)))
    logging.debug("       in the directory {0}".format(os.getcwd()))

    global visible_mode
    if visible_mode:
        logging.info(comment)
        code = subprocess.call(commandline)
    else:
        log_file_name = temporaries.create_temporary_file("process.log")

        global latency
        timer = RepeatingTimer(latency, progress_bar_print)
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


def silent_call(commandline):
    code = call("", commandline)
    return code


def pipe_call(comment, commandline_from, commandline_to):
    """
    Calls two commands redirecting the output of first command to the second
    one.

    @param comment              The comment that the user will see.
    @param commandline_from     The first command.
    @param commandline_to       The second command.
    """
    code = 0
    global counter
    counter = 1
    global bar_comment
    bar_comment = comment
    logging.debug("Running the command: {0} | "
                  "{1}".format(" ".join(commandline_from),
                               " ".join(commandline_to)))
    logging.debug("       in the directory {0}".format(os.getcwd()))
    log_file_name = temporaries.create_temporary_file("process.log")

    global latency
    timer = RepeatingTimer(latency, progress_bar_print)
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


def silent_pipe_call(commandline_from, commandline_to):
    pipe_call("", commandline_from, commandline_to)


def function_call(comment, function, *arguments):
    """
    Calls the funciton with the given arguments.

    @param comment              The comment that the user will see.
    @param function             The function.
    @param arguments            Its arguments.
    @return                     The return value of the called function.
    """
    global counter
    counter = 1
    global bar_comment
    bar_comment = comment
    global latency
    timer = RepeatingTimer(latency, progress_bar_print)
    timer.daemon = True
    timer.start()
    result = function(*arguments)
    timer.cancel()
    sys.stdout.write("\n")
    return result


def silent_function_call(function, *arguments):
    result = function_call("", function, *arguments)
    return result


def function_call_list(comment, function, tasks):
    len_name_max = 30
    num_pluses_max = 25
    i_task = 1
    sys.stdout.write('\n')
    for task in tasks:
        sys.stdout.write("\r")
        ratio = float(i_task) / float(len(tasks))
        num_pluses = int(float(ratio) * float(num_pluses_max))
        pluses = "{s:+<{n}}".format(s="", n=num_pluses)
        progress = "[{0}/{1}]".format(i_task, len(tasks))
        sys.stdout.write(
            "{comment}: {name: <{len_name}.{len_name}} "
            "{bar: <{len_bar}.{len_bar}} "
            "{progress: >{len_progress}."
            "{len_progress}}".format(comment=comment, name=task[0],
                                     len_name=len_name_max, bar=pluses,
                                     len_bar=num_pluses_max, progress=progress,
                                     len_progress=len(progress)))
        sys.stdout.flush()
        arguments = task[1:]
        function(*arguments)
        i_task += 1
    sys.stdout.write('\n')
