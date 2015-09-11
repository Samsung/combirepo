#!/usr/bin/env python2.7
# -*- coding: utf-8 -*-
import os
import shutil
import re
import logging


class KickstartFile():
    """
    Simple set of functions for simple manipulations with kickstart files.
    """
    def __init__(self, path):
        """
        Initializes the kickstart file.

        @param path The path to the kickstart file.
        """
        self.path = path

    def get_repository_names(self):
        """
        Gets the names of repositories that are mentioned in the kickstart
        file.
        """
        with open(self.path, "r") as kickstart_file:
            names = []
            for line in kickstart_file:
                if line.startswith("repo "):
                    names.extend(re.findall(r"--name=(\S+)", line))
            return names

    def replace_repository_paths(self, repository_names, repository_paths):
        """
        Replaces the paths to the repository with given names with to the given
        paths in the kickstart file.

        @param repository_names     The list of repository names.
        @param repository_paths     The list of corresponding repository paths
                                    (must be local).
        """
        lines = []

        with open(self.path, "r") as kickstart_file:
            for line in kickstart_file:
                if line.startswith("repo "):
                    for i in range(len(repository_names)):
                        if " --name={0} ".format(repository_names[i]) in line:
                            path = repository_paths[i]
                            line = re.sub(r'\s+--baseurl=\S+\s+',
                                          r" --baseurl=file://"
                                          "{0} ".format(path),
                                          line)
                            logging.debug("Writting the following line to "
                                          "kickstart file: \n{0}".format(line))
                    lines.append(line)
                else:
                    lines.append(line)

        with open(self.path, "w") as kickstart_file:
            kickstart_file.writelines(lines)

    def comment_all_groups(self):
        """
        Comments all lines in %packages section that begin with '@' symbol.
        """
        lines = []

        with open(self.path, "r") as kickstart_file:
            if_packages_section = False
            for line in kickstart_file:
                if if_packages_section:
                    if line.startswith("%end"):
                        if_packages_section = False
                        lines.append(line)
                    elif line.startswith("@"):
                        lines.append("#{0}".format(line))
                    else:
                        lines.append(line)
                elif line.startswith("%packages"):
                    if_packages_section = True
                    lines.append(line)
                else:
                    lines.append(line)

        with open(self.path, "w") as kickstart_file:
            kickstart_file.writelines(lines)

    def add_packages(self, packages):
        """
        Adds the given list of packages to the %packages section of the
        kickstart file.

        @param packages The list of packages that must be added.
        """
        lines = []

        with open(self.path, "r") as kickstart_file:
            for line in kickstart_file:
                if line.startswith("%packages"):
                    lines.append(line)
                    for package in packages:
                        lines.append("{0}\n".format(package))
                else:
                    lines.append(line)

        with open(self.path, "w") as kickstart_file:
            kickstart_file.writelines(lines)
