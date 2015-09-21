#!/usr/bin/env python2.7
# -*- coding: utf-8 -*-
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
    Combi-repo parameters are the characterization of combi-repo's behaviour at
    run-time. Command line and config parsing construct this structure and then
    the tool runs using it only.
    """
    def __init__(self):
        """
        Initializes the combi-repo parameters (does nothing).
        """
        self._profile_name = None
        self._temporary_directory_path = None
        self._repository_supplementary_url = None
        self._package_names = {}
        self._repository_pairs = []
        self._architecture = None
        self._kickstart_file_path = None
        self._output_directory_path = None
        self._mic_options = []
        self._greedy_mode = False
        self._mirror_mode = False
        self._prefer_strategy = None

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
    def temporary_directory_path(self):
        """The directory where combi-repo stores its cache."""
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
    def repository_supplementary_url(self):
        """The URL of the repository with supplementray packages."""
        return self._repository_supplementary_url

    @repository_supplementary_url.setter
    def repository_supplementary_url(self, value):
        # FIXME: check valid URL.
        self._repository_supplementary_url = value

    @repository_supplementary_url.deleter
    def repository_supplementary_url(self):
        del self._repository_supplementary_url

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
        check.file_exists(value)
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
        if value is not list:
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
    def prefer_strategy(self):
        """The identifier of preferring strategy to be used."""
        return self._prefer_strategy

    @prefer_strategy.setter
    def prefer_strategy(self, value):
        if value not in valid_prefer_strategies:
            logging.error("Invalid preferring strategy. Possible are:")
            for strategy in valid_prefer_strategies:
                logging.error(" * {0}".format(strategy))
            sys.exit("Error.")
        self._prefer_strategy = value

    @prefer_strategy.deleter
    def prefer_strategy(self):
        del self._prefer_strategy

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

    def __add__(self, properties):
        """
        Merges two properties structure in the sence that second has bigger
        priority.

        @param properties       The second properties structure.
        @return                 The merged properties structure.
        """
        if properties.profile_name is not None:
            self._profile_name = properties.profile_name

        if self._temporary_directory_path is None:
            path = properties.temporary_directory_path
            self._temporary_directory_path = path
        elif properties.temporary_directory_path is not None:
            path = properties.temporary_directory_path
            self.__warn_about_merging_strategy(path)

        if self._repository_supplementary_url is None:
            url = properties.repository_supplementary_url
            self._repository_supplementary_url = url
        elif properties.repository_supplementary_url is not None:
            url = properties.repository_supplementary_url
            self.__warn_about_merging_strategy(url)

        if len(self._package_names.keys()) == 0:
            self._package_names = properties.package_names
        elif len(self._package_names.keys()) > 0:
            length_total = 0
            for key in self._package_names.keys():
                length_total = length_total + len(self._package_names[key])
            if length_total > 0:
                length_total = 0
                for key in properties.package_names.keys():
                    length_total = (length_total +
                                    len(properties.package_names[key]))
                if length_total > 0:
                    package_names = properties.package_names
                    self.__warn_about_merging_strategy(package_names)
            else:
                self._package_names = properties.package_names

        if len(self._repository_pairs) == 0:
            self._repository_pairs = properties.repository_pairs
        elif len(properties.repository_pairs) > 0:
            self.__warn_about_merging_strategy(properties.repository_pairs)

        if self._architecture is None:
            self._architecture = properties.architecture
        elif (properties.architecture is not None and
                properties.architecture != self._architecture):
            self.__warn_about_merging_strategy(properties.architecture)

        if self._kickstart_file_path is None:
            self._kickstart_file_path = properties.kickstart_file_path
        elif (properties.kickstart_file_path is not None and
                (properties.kickstart_file_path != self._kickstart_file_path)):
            self.__warn_about_merging_strategy(properties.kickstart_file_path)

        if self._output_directory_path is None:
            self._output_directory_path = properties.output_directory_path
        elif (properties.output_directory_path is not None and
                (properties.output_directory_path
                    != self._output_directory_path)):
            path = properties.output_directory_path
            self.__warn_about_merging_strategy(path)

        if len(self._mic_options) == 0:
            self._mic_options = properties.mic_options
        elif properties.mic_options is not None:
            self.__warn_about_merging_strategy(properties.mic_options)

        if not self._greedy_mode:
            self._greedy_mode = properties.greedy_mode
        elif properties.greedy_mode:
            self.__warn_about_merging_strategy("greedy = 1")

        if not self._mirror_mode:
            self._mirror_mode = properties.mirror_mode
        elif properties.mirror_mode:
            self.__warn_about_merging_strategy("mirror = 1")

        if self._prefer_strategy is None:
            self._prefer_strategy = properties.prefer_strategy
        elif properties.prefer_strategy:
            self.__warn_about_merging_strategy(properties.prefer_strategy)

        return self
