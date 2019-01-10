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
import logging
from sets import Set
import check
import strings
from repository_pair import RepositoryPair


valid_package_keys = ["forward", "backward", "single", "excluded", "service",
                      "preferable"]

valid_prefer_strategies = ["small", "big"]


class RepositoryCombinerParameters(object):
    """
    Combi-repo parameters are the characterization of combirepo's behaviour at
    run-time. Command line and config parsing construct this structure and then
    the tool runs using it only.
    """
    def __init__(self):
        """
        Initializes the combirepo parameters (does nothing).
        """
        self._profile_name = None
        self._user = None
        self._password = None
        self._temporary_directory_path = None
        self._sup_repo_url = None
        self._package_groups = {}
        self._package_names = {}
        self._repository_pairs = []
        self._architecture = None
        self._kickstart_file_path = None
        self._output_directory_path = None
        self._mic_options = []
        self._greedy_mode = False
        self._mirror_mode = False
        self._preferring_strategy = None

    @property
    def profile_name(self):
        """The name of profile in config file."""
        return self._profile_name

    @profile_name.setter
    def profile_name(self, value):
        self._profile_name = value

    @profile_name.deleter
    def profile_name(self):
        del self._profile_name

    @property
    def user(self):
        """The user name at the download server."""
        return self._user

    @user.setter
    def user(self, value):
        self._user = value

    @user.deleter
    def user(self):
        del self._user

    @property
    def password(self):
        """The password at the download server."""
        return self._password

    @password.setter
    def password(self, value):
        self._password = value

    @password.deleter
    def password(self):
        del self._password

    @property
    def temporary_directory_path(self):
        """The directory where combirepo stores its cache."""
        if self._temporary_directory_path is not None:
            check.directory_exists(self._temporary_directory_path)
        return self._temporary_directory_path

    @temporary_directory_path.setter
    def temporary_directory_path(self, path):
        check.directory_exists(path)
        self._temporary_directory_path = path

    @temporary_directory_path.deleter
    def temporary_directory_path(self):
        del self._temporary_directory_path

    @property
    def sup_repo_url(self):
        """The URL of the repository with supplementray packages."""
        return self._sup_repo_url

    @sup_repo_url.setter
    def sup_repo_url(self, value):
        if value is None:
            self._sup_repo_url = None
        elif os.path.isdir(value):
            self._sup_repo_url = os.path.abspath(value)
        else:
            check.valid_url_string(value)
            self._sup_repo_url = value

    @sup_repo_url.deleter
    def sup_repo_url(self):
        del self._sup_repo_url

    @property
    def package_groups(self):
        """
        The names of package groups that must be treated specially
        """
        return self._package_groups

    @package_groups.setter
    def package_groups(self, package_groups):
        if not isinstance(package_groups, dict):
            logging.warning("Argument package_groups is not a dictionary!")
            return
        for key in package_groups.keys():
            if not isinstance(package_groups[key], list):
                continue
            for package_group in package_groups[key]:
                check.valid_ascii_string(package_group)
        self._package_groups = package_groups

    @package_groups.deleter
    def package_groups(self):
        del self._package_groups

    @property
    def package_names(self):
        """
        The names of packages that must be treated specially
        """
        return self._package_names

    @package_names.setter
    def package_names(self, package_names):
        if not isinstance(package_names, dict):
            raise Exception("Argument is not a dictionary!")
        global valid_package_keys
        for key in valid_package_keys:
            self._package_names[key] = Set()
        for key in package_names.keys():
            if key not in valid_package_keys:
                raise Exception("Unsupported key for package name: {0}, "
                                "supported keys are: "
                                "{1}".format(key, valid_package_keys))
            if not isinstance(package_names[key], list):
                continue
            for package_name in package_names[key]:
                # FIXME: check valid RPM package name
                check.valid_ascii_string(package_name)
                if package_name in self._package_names[key]:
                    logging.warning("Package {0} is listed more than "
                                    "once!".format(package_name))
                else:
                    union = self._package_names[key] | Set([package_name])
                    self._package_names[key] = union

    @package_names.deleter
    def package_names(self):
        del self._package_names

    @property
    def repository_pairs(self):
        """The pairs of combined repositories."""
        return self._repository_pairs

    @repository_pairs.setter
    def repository_pairs(self, pairs):
        for pair in pairs:
            if type(pair) is not RepositoryPair:
                raise Exception("One of pairs is not the repository pair.")
            self._repository_pairs.append(pair)

    @repository_pairs.deleter
    def repository_pairs(self):
        del self._repository_pairs

    @property
    def architecture(self):
        """The architecture of the image to be built."""
        return self._architecture

    @architecture.setter
    def architecture(self, value):
        # FIXME: add check that the architecture is known.
        self._architecture = value

    @architecture.deleter
    def architecture(self):
        del self._architecture

    @property
    def kickstart_file_path(self):
        """The path to the kickstart file to be used by MIC."""
        return self._kickstart_file_path

    @kickstart_file_path.setter
    def kickstart_file_path(self, value):
        self._kickstart_file_path = value

    @kickstart_file_path.deleter
    def kickstart_file_path(self):
        del self._kickstart_file_path

    @property
    def output_directory_path(self):
        """The path to output directory for MIC."""
        return self._output_directory_path

    @output_directory_path.setter
    def output_directory_path(self, value):
        check.directory_exists(value)
        self._output_directory_path = value

    @output_directory_path.deleter
    def output_directory_path(self):
        del self._output_directory_path

    @property
    def mic_options(self):
        """The additional options for MIC."""
        return self._mic_options

    @mic_options.setter
    def mic_options(self, value):
        if not isinstance(value, list):
            raise Exception("Argument is not a list!")
        self._mic_options = value

    @mic_options.deleter
    def mic_options(self):
        del self._mic_options

    @property
    def greedy_mode(self):
        """The flag that controlls whether the gredy mode is on."""
        return self._greedy_mode

    @greedy_mode.setter
    def greedy_mode(self, value):
        self._greedy_mode = value
        if self._greedy_mode:
            self._mirror_mode = True

    @greedy_mode.deleter
    def greedy_mode(self):
        del self._greedy_mode

    @property
    def mirror_mode(self):
        """The flag that controlls whether the mirror mode is on."""
        return self._mirror_mode

    @mirror_mode.setter
    def mirror_mode(self, value):
        if not self._greedy_mode:
            self._mirror_mode = value

    @mirror_mode.deleter
    def mirror_mode(self):
        del self._mirror_mode

    @property
    def preferring_strategy(self):
        """The identifier of preferring strategy to be used."""
        return self._preferring_strategy

    @preferring_strategy.setter
    def preferring_strategy(self, value):
        if value not in valid_prefer_strategies:
            logging.error("Invalid preferring strategy. Possible are:")
            for strategy in valid_prefer_strategies:
                logging.error(" * {0}".format(strategy))
            sys.exit("Error.")
        self._preferring_strategy = value

    @preferring_strategy.deleter
    def preferring_strategy(self):
        del self._preferring_strategy

    def __warn_about_merging_strategy(self, argument):
        """
        Prints a warning about merging strategy.
        """
        warning_message = ["Commandline arguments are preferred to config: "]
        if isinstance(argument, str):
            warning_message.append(" * {0} from config file will be "
                                   "   ignored!".format(argument))
        elif isinstance(argument, list):
            for node in argument:
                warning_message.append(" * {0} from config file will be "
                                       "   ignored!\n".format(node))
        elif isinstance(argument, dict):
            for key in argument.keys():
                warning_message.append(" * {0} : {1} from config file will be "
                                       "   ignored!\n".format(key,
                                                              argument[key]))
        else:
            warning_message.append(" * Some argument from config file will be "
                                   "   ignored!")
        logging.warning("".join(warning_message))

    def __add__(self, parameters):
        """
        Merges two parameters structure in the sence that second has bigger
        priority.

        @param parameters       The second parameters structure.
        @return                 The merged parameters structure.
        """
        if parameters.profile_name is not None:
            self._profile_name = parameters.profile_name

        if self._temporary_directory_path is None:
            path = parameters.temporary_directory_path
            self._temporary_directory_path = path
        elif parameters.temporary_directory_path is not None:
            path = parameters.temporary_directory_path
            self.__warn_about_merging_strategy(path)

        if self._sup_repo_url is None:
            url = parameters.sup_repo_url
            self._sup_repo_url = url
        elif parameters.sup_repo_url is not None:
            url = parameters.sup_repo_url
            self.__warn_about_merging_strategy(url)
        if self._user is None:
            self._user = parameters.user
        elif parameters.user is not None:
            self.__warn_about_merging_strategy(parameters.user)
        if self._password is None:
            self._password = parameters.password
        elif parameters.password is not None:
            self.__warn_about_merging_strategy(parameters.password)

        if len(self._package_groups) == 0:
            self._package_groups = parameters.package_groups
        elif len(parameters.package_groups) > 0:
            self.__warn_about_merging_strategy(parameters.package_groups)

        if len(self._package_names.keys()) == 0:
            self._package_names = parameters.package_names
        elif len(self._package_names.keys()) > 0:
            length_total = 0
            for key in self._package_names.keys():
                length_total = length_total + len(self._package_names[key])
            if length_total > 0:
                length_total = 0
                for key in parameters.package_names.keys():
                    length_total = (length_total +
                                    len(parameters.package_names[key]))
                if length_total > 0:
                    package_names = parameters.package_names
                    self.__warn_about_merging_strategy(package_names)
            else:
                self._package_names = parameters.package_names

        if len(self._repository_pairs) == 0:
            self._repository_pairs = parameters.repository_pairs
        elif len(parameters.repository_pairs) > 0:
            self.__warn_about_merging_strategy(parameters.repository_pairs)

        if self._architecture is None:
            self._architecture = parameters.architecture
        elif (parameters.architecture is not None and
                parameters.architecture != self._architecture):
            self.__warn_about_merging_strategy(parameters.architecture)

        if self._kickstart_file_path is None:
            self._kickstart_file_path = parameters.kickstart_file_path
        elif (parameters.kickstart_file_path is not None and
                (parameters.kickstart_file_path != self._kickstart_file_path)):
            self.__warn_about_merging_strategy(parameters.kickstart_file_path)

        if self._output_directory_path is None:
            self._output_directory_path = parameters.output_directory_path
        elif (parameters.output_directory_path is not None and
                (parameters.output_directory_path !=
                 self._output_directory_path)):
            path = parameters.output_directory_path
            self.__warn_about_merging_strategy(path)

        if len(self._mic_options) == 0:
            self._mic_options = parameters.mic_options
        elif parameters.mic_options is not None:
            self.__warn_about_merging_strategy(parameters.mic_options)

        if not self._greedy_mode:
            self._greedy_mode = parameters.greedy_mode
        elif parameters.greedy_mode:
            self.__warn_about_merging_strategy("greedy = 1")

        if not self._mirror_mode:
            self._mirror_mode = parameters.mirror_mode
        elif parameters.mirror_mode:
            self.__warn_about_merging_strategy("mirror = 1")

        if self._preferring_strategy is None:
            self._preferring_strategy = parameters.preferring_strategy
        elif parameters.preferring_strategy:
            self.__warn_about_merging_strategy(parameters.preferring_strategy)

        return self
