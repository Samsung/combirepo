#!/usr/bin/env python2.7
# -*- coding: utf-8 -*-
import os
import sys
import logging
import configparser
import difflib
import strings
import check
from parameters import RepositoryCombinerParameters, valid_package_keys
from repository_pair import RepositoryPair


default_path = "~/.combirepo.conf"


def initialize_config(config_file_path):
    """
    Checks the given config and initializes it if it is not set and does not
    exist.

    @param config_file_path The path to config file, or None in case the
                            default onw should be used.
    """
    help_url = "http://confluence.rnd.samsung.ru/display/TC/Config+file+format"
    global default_path
    if config_file_path is None:
        config_file_path = os.path.expanduser(default_path)
        if not os.path.isfile(config_file_path):
            logging.warning("Default config {0} does not exist! It will "
                            "be generated, but you should complete it with "
                            "repository paths, package names and other "
                            " options.".format(config_file_path))
            config = configparser.SafeConfigParser(allow_no_value=True)
            config.add_section('general')
            config.set('general', '# See documentation about combirepo '
                       'config file format at page {0}'.format(help_url))
            with open(config_file_path, 'wb') as config_file:
                config.write(config_file)
    else:
        config_file_path = os.path.expanduser(config_file_path)
        check.file_exists(config_file_path)

    default_path = config_file_path


class ConfigParser():
    """
    Combi-repo config parser.
    """
    def __init__(self):
        """
        Initializes the config parser.

        @param path The path to the config file.
        """
        self.path = default_path
        self.parser = configparser.SafeConfigParser()

    def __warn_about_existing(self, name, names_existing):
        """
        Warns the user about the possible typos in the config file.

        @param name             The string that is searched in the config file.
        @param names_existing   The list of string that actually present in
                                the config file.
        """
        for name_existing in names_existing:
            ratio = difflib.SequenceMatcher(None, name, name_existing).ratio()
            if ratio > 0.8 or name_existing in name or name in name_existing:
                logging.warning("Hint: maybe there is a typo. Your variant: "
                                "{0}, proper is "
                                "{1}".format(name_existing, name))

    def __check_section_exists(self, section_name):
        """
        Checks whether the section with the given name exists in the given
        config file.

        @param section_name The name of section.
        """
        if not self.parser.has_section(section_name):
            logging.error("Config file {0} does not contain [{1}] "
                          "section.".format(self.path, section_name))
            self.__warn_about_existing(section_name, self.parser.sections())
            sys.exit("Error.")

    def __check_option_exists(self, section_name, option_name):
        """
        Checks whether the option with the given name exists in the section
        with the given name in the given config file.

        @param section_name     The name of section.
        @param option_name      The name of option.
        """
        if not self.parser.has_option(section_name, option_name):
            logging.error("Config file {0} does not contain option "
                          "\"{1}\" in the section "
                          "[{2}]".format(self.path, option_name,
                                         section_name))
            self.__warn_about_existing(option_name,
                                       self.parser.options(section_name))
            sys.exit("Error.")

    def __get_list(self, section_name, option_name):
        """
        Gets the list of option arguments and splits it to the list.

        @param section_name     The name of section.
        @param option_name      The name of option.
        @return                 The list of option arguments.
        """
        if self.parser.has_option(section_name, option_name):
            argument_string = self.parser.get(section_name, option_name)
            argument_list = strings.split_names(argument_string)
            logging.debug("Detected list {0}".format(argument_list))
            return argument_list
        else:
            self.__warn_about_existing(option_name,
                                       self.parser.options(section_name))
            return []

    def __build_repository_pairs(self, repository_aliases):
        """
        Parses repository sections and builds repository pairs from them.

        @param repository_aliases   The list of repository aliases.
        @return                     The list of repository pairs.
        """
        # Parse repository sections:
        repository_pairs = []
        for repository_alias in repository_aliases:
            repository_pair = RepositoryPair()
            repository_pair.alias = repository_alias
            self.__check_section_exists(repository_alias)
            logging.debug("Detected repository {0}".format(repository_alias))
            self.__check_option_exists(repository_alias, "name")
            repository_pair.name = self.parser.get(repository_alias, "name")
            logging.debug("Detected repository name "
                          "{0}".format(repository_pair.name))
            self.__check_option_exists(repository_alias, "url_orig")
            repository_pair.url = self.parser.get(repository_alias,
                                                  "url_orig")
            self.__check_option_exists(repository_alias, "url_marked")
            repository_pair.url_marked = self.parser.get(repository_alias,
                                                         "url_marked")
            repository_pairs.append(repository_pair)
        return repository_pairs

    def parse(self):
        """
        Parses the given config file and returns the properties structure.

        @return     The parameters structure of combirepo tool.
        """
        check.file_exists(self.path)
        self.parser.read(self.path)
        parameters = RepositoryCombinerParameters()

        # Parse general section:
        self.__check_section_exists("general")
        self.__check_option_exists("general", "profile")
        parameters.profile_name = self.parser.get("general", "profile")

        # Parse profile section:
        profile_name = parameters.profile_name
        self.__check_section_exists(profile_name)
        logging.debug("Detected profile "
                      "{0}".format(profile_name))
        self.__check_option_exists(profile_name, "repos")
        repository_aliases = self.__get_list(profile_name, "repos")

        if self.parser.has_option(profile_name, "repo_supplementary"):
            parameters.sup_repo_url = self.parser.get(profile_name,
                                                      "repo_supplementary")

        if self.parser.has_option(profile_name, "architecture"):
            parameters.architecture = self.parser.get(profile_name,
                                                      "architecture")

        if self.parser.has_option(profile_name, "kickstart"):
            kickstart_file_path = self.parser.get(profile_name, "kickstart")
            parameters.kickstart_file_path = kickstart_file_path

        if self.parser.has_option(profile_name, "out_dir"):
            output_directory_path = self.parser.get(profile_name, "out_dir")
            parameters.output_directory_path = output_directory_path

        mic_options = self.__get_list(profile_name, "mic_options")

        if self.parser.has_option(profile_name, "greedy"):
            greedy_mode = self.parser.getboolean(profile_name, "greedy")
            parameters.greedy_mode = greedy_mode

        if self.parser.has_option(profile_name, "mirror"):
            mirror_mode = self.parser.getboolean(profile_name, "mirror")
            parameters.mirror_mode = mirror_mode

        if self.parser.has_option(profile_name, "preferring_strategy"):
            preferring_strategy = self.parser.get(profile_name,
                                                  "preferring_strategy")
            parameters.preferring_strategy = preferring_strategy

        package_names = {}
        for key in valid_package_keys:
            names = self.__get_list(parameters.profile_name,
                                    "{0}_packages".format(key))
            package_names[key] = names
        parameters.package_names = package_names
        logging.debug("Package names from config: "
                      "{0}".format(parameters.package_names))

        repository_pairs = self.__build_repository_pairs(repository_aliases)
        parameters.repository_pairs = repository_pairs

        return parameters
