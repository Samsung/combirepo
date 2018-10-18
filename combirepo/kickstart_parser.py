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
import shutil
import re
import logging
from operator import itemgetter


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

    def get_images_mount_points(self):
        """
        Gets the names of images and corresponding mount points
        that are mentioned in the kickstart file.
        """
        with open(self.path, "r") as kickstart_file:
            images_dict_list = []
            for line in kickstart_file:
                if line.startswith("part /"):
                    image = re.findall(r"--label=(\S+)", line)
                    mount_point = re.findall(r"/(\S*)", line)
                    if image and mount_point:
                        depth = 0
                        if mount_point[0]:
                            mount_path = os.path.normpath(mount_point[0]).strip('/')
                            depth = len(mount_path.split('/'))
                        images_dict_list.append({'name':  image[0] + '.img',
                                                 'mount_point': mount_point[0],
                                                 'depth': depth})
                    else:
                        logging.warning("Could not find image info in {0}".format(line))
            sorted_images_dict_list = []
            if len(images_dict_list):
                sorted_images_dict_list = sorted(images_dict_list, key=itemgetter('depth'))
            logging.debug("Found these images: {0}".format(sorted_images_dict_list))

            return sorted_images_dict_list

    def replace_repository_paths(self, repository_names, repository_paths):
        """
        Replaces the paths to the repository with given names with to the given
        paths in the kickstart file.

        @param repository_names     The list of repository names.
        @param repository_paths     The list of corresponding repository paths
                                    (must be local).
        """
        lines = []
        if repository_names is None or len(repository_names) == 0:
            logging.error("No repository names are given! "
                          "{0}".format(repository_names))

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

    def prepend_repository_path(self, repository_name, repository_path):
        """
        Adds the path to thre repository with given name and path.

        @param repository_name      Repository name.
        @param repository_path      Repository path.
        """
        lines = []
        with open(self.path, "r") as kickstart_file:
            if_added = False
            for line in kickstart_file:
                if line.startswith("repo "):
                    if not if_added:
                        lines.append(
                            "repo --name={0} --baseurl=file://{1} --save "
                            "--ssl_verify=no\n".format(repository_name,
                                                       repository_path))
                        if_added = True
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
                        logging.debug("Added line #{0}".format(line))
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
                        logging.debug("Added package {0}".format(package))
                else:
                    lines.append(line)

        with open(self.path, "w") as kickstart_file:
            kickstart_file.writelines(lines)
