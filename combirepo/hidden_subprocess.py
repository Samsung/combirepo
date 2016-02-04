#!/usr/bin/env python2.7
# -*- coding: utf-8 -*-
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA 02111-1307, USA.
#
# Copyright (C) Samsung Electronics, 2016
#
# 2016         Ilya Palachev                 <i.palachev@samsung.com>

import os
import sys
import subprocess
import multiprocessing
import multiprocessing.pool
import threading
import logging
import time
import temporaries

"""In visible mode output from process is printed to stdout and stderr."""
visible_mode = False
"""The latency of status update checking progress bar re-printing."""
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

    def stop(self):
        self.function(*self.args, **self.kwargs)


"""The number progress symbol that should be printed."""
counter = 1
"""The comment for the progress bar."""
bar_comment = ""
"""The default comment to be printed if something is done."""
default_bar_comment = "Processing, please wait"


def progress_bar_print():
    """
    Prints the simple progress bar to the stdout.
    """
    progress_symbols = ['|', '/', '—', '\\']
    sys.stdout.write("\r")
    global counter
    if counter == 0:
        progress_symbol = '+'
    else:
        progress_symbol = progress_symbols[counter % len(progress_symbols)]
    progress = "[ " + progress_symbol + " ]"
    if bar_comment == "":
        comment = default_bar_comment
    else:
        comment = bar_comment
    progress_bar = comment + " " + progress
    sys.stdout.write(' ' * 100)
    sys.stdout.write("\r")
    sys.stdout.flush()
    sys.stdout.write(progress_bar)
    sys.stdout.flush()
    counter = counter + 1


def progress_bar_print_final():
    global counter
    counter = 0
    progress_bar_print()


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

        if code != 0:
            logging.error("The subprocess failed!")
            logging.error("STDERR output:")
            with open(log_file_name, 'r') as log_file:
                logging.error("{0}".format(log_file.read()))

    progress_bar_print_final()
    sys.stdout.write('\n')
    return code


def silent_call(commandline):
    """
    Calls the command without printing any comments.

    @param commandline      The command line to be called.
    @return                 The return code of command.
    """
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
    progress_bar_print_final()
    sys.stdout.write('\n')


def silent_pipe_call(commandline_from, commandline_to):
    """
    Calls two commands redirecting the output of first command to the second
    one and does not prints any comments.

    @param commandline      The command line to be called.
    @return                 The return code of command.
    """
    pipe_call("", commandline_from, commandline_to)


def function_call(comment, function, *arguments):
    """
    Calls the funciton with the given arguments.

    @param comment              The comment that the user will see.
    @param function             The function.
    @param arguments            Its arguments.
    @return                     The return value of the called function.
    """
    sys.stdout.write('\n')
    time_start = time.time()
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
    progress_bar_print_final()
    sys.stdout.write('\n')
    time_elapsed = time.time() - time_start
    logging.info("Function {0} with comment \"{1}\" has taken "
                 "{2}".format(function.__name__, comment, time_elapsed))
    return result


def silent_function_call(function, *arguments):
    """
    Calls the funciton with the given arguments without printing any comments.

    @param function             The function.
    @param arguments            Its arguments.
    @return                     The return value of the called function.
    """
    result = function_call("", function, *arguments)
    return result


def print_status(comment, name, n_tasks_done, n_tasks):
    """
    Prints progress bar status.

    @param comment      Comment about what is being done.
    @param name         The name of task.
    @param n_tasks_done The number of completed tasks.
    @param n_tasks      The total number of tasks
    """
    len_comment_max = 20
    len_name_max = 30
    num_pluses_max = 25
    sys.stdout.write("\r")
    ratio = float(n_tasks_done) / float(n_tasks)
    num_pluses = int(float(ratio) * float(num_pluses_max))
    pluses = "{s:+<{n}}".format(s="", n=num_pluses)
    len_tasks_max = 6
    if len(str(n_tasks)) > len_tasks_max:
        len_tasks_max = len(str(n_tasks))
    sys.stdout.write(
        "{comment: <{len_comment}.{len_comment}}: "
        "{name: <{len_name}.{len_name}} "
        "{bar: <{len_bar}.{len_bar}} "
        "[{n_tasks_done: >{len_tasks}.{len_tasks}}/"
        "{n_tasks: <{len_tasks}.{len_tasks}}]".format(
            comment=comment, len_comment=len_comment_max, name=name,
            len_name=len_name_max, bar=pluses, len_bar=num_pluses_max,
            n_tasks_done=str(n_tasks_done), n_tasks=str(n_tasks),
            len_tasks=len_tasks_max))
    sys.stdout.flush()


def function_call_list(comment, function, tasks):
    """
    Calls the function for each element of the task list.

    @param comment      Comment about what is being done.
    @param function     The function to be called.
    @param tasks        The list of tuples (name, arguments) where name will
                        be printed in progress bar and arguments will be passed
                        to the funciton call.
    """
    i_task = 1
    for task in tasks:
        print_status(comment, task[0], i_task, len(tasks))
        arguments = task[1:]
        function(*arguments)
        i_task += 1
    sys.stdout.write("\n")


"""The function that is called to get the status of the process."""
global_status_callback = None


def print_status_dynamic():
    """
    Gets the status from callback and prints it in the progress bar.
    """
    comment, name, n_tasks_done, n_tasks = global_status_callback()
    print_status(comment, name, n_tasks_done, n_tasks)


def function_call_monitor(function, arguments, status_callback):
    """
    Calls the function with arguments and monitors its status using the given
    callback.

    @param function         The function to be called.
    @param arguments        Its arguments to be passed to it.
    @param status_callback  The callback for getting the status of the
                            process.
    """
    global global_status_callback
    global_status_callback = status_callback
    timer = RepeatingTimer(latency, print_status_dynamic)
    timer.daemon = True
    timer.start()
    function(*arguments)
    timer.cancel()
    sys.stdout.write('\n')
