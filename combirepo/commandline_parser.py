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
import re
import argparse
import sys
import logging
import atexit
import temporaries
import hidden_subprocess
from strings import split_names_list
from parameters import RepositoryCombinerParameters
import rpm_patcher
import config_parser
from repository_pair import RepositoryPair
import repository_combiner
import files
import repository_manager

man_format_remove = re.compile(r'(\\f\w)|(\n\.[A-Z]{2}\n?)')


class SmartFormatter(argparse.HelpFormatter):
    def _split_lines(self, text, width):
        text = re.sub(man_format_remove, '', text)
        # this is the RawTextHelpFormatter._split_lines
        if text.startswith('R|'):
            return text[2:].splitlines()
        return argparse.HelpFormatter._split_lines(self, text, width)


def convert_list_to_sequential_tuples(flat_list, tuple_length):
    """
    Groups a list into consecutive n-tuples, e.g.:
    ([0,3,4,10,2,3], 2) => [(0,3), (4,10), (2,3)]

    Incomplete tuples are discarded, e.g.:
    (range(10), 3) => [(0, 1, 2), (3, 4, 5), (6, 7, 8)]

    @param flat_list    The flat list.
    @param tuple_length The length of generated tuples.

    @return             The list of tuples constructed from original flat
                        list.
    """
    return zip(*[flat_list[i::tuple_length] for i in range(tuple_length)])


class CommandlineParser():
    """
    The parser of command-line arguments for combirepo tool.
    """
    def __init__(self):
        """
        Initializes the parser and saves arguments for future use if needed
        """
        self._parser = None
        self._parser_formatter_class = SmartFormatter

    def get_formatted_parser(self, formatter_class):
        """
        Create a parser with custom help formatter

        Used to generate man pages
        """
        self._parser_formatter_class = formatter_class
        self.__prepare_parser()
        return self._parser

    def __register_positional_arguments(self):
        """
        Register positional arguments.
        """
        self._parser.add_argument(
            "triplets", type=str, nargs='*', help="R|Triplets: \n\n"
            "triplet_1 triplet_2 ... triplet_i ... triplet_n\n\n"
            "where each triplet has the following form:\n\n"
            "NAME URL_ORIG URL_MARKED\n\n"
            "where:\n"
            "1. NAME       is the name of repository as specified in \n"
            "              kickstart file, \n"
            "2. URL_ORIG   is the path (if it is located locally)\n"
            "              or the URL  (if it is located remotely)\n"
            "              to the original repository, \n"
            "3. URL_MARKED is the path (if it is located locally)\n"
            "              or the URL  (if it is located remotely)\n"
            "              to the marked repository.")

    def __register_package_name_options(self):
        """
        Registers options that controll package name handling.
        """
        self._parser.add_argument(
            "-f", "--forward", type=str, action="append", help="The name of "
            "package that should be marked with all its forward dependencies")
        self._parser.add_argument(
            "-b", "--backward", type=str, action="append", help="The name of "
            "package that should be marked with all its backward dependencies "
            "(i. e. dependees)")
        self._parser.add_argument(
            "-s", "--single", type=str, action="append", help="The name of "
            "package that should be marked")
        self._parser.add_argument(
            "-e", "--exclude", type=str, action="append", help="The name of "
            "package that should be excluded from the final list of marked "
            "packages.")
        self._parser.add_argument(
            "-S", "--service", type=str, action="append", help="The name of "
            "package that are not installed to the mage by default, but that "
            "must be installed in this build. The sample is \\fBlibasan\\fR "
            "package used for builds with Address Sanitizer support.")
        self._parser.add_argument(
            "-p", "--preferable-packages", action="append", type=str,
            dest="preferable", help="The name of package that should be "
            "prefered in case of \"have choice\" problem.")
        self._parser.add_argument(
            "--packages-file", action="store", type=str,
            dest="packages_file", help="The file containing list of snapshot packages "
            "that should be downloaded from repositories.")

    def __register_program_run_options(self):
        """
        Registers the options that controll the program run.
        """
        self._parser.add_argument(
            "-v", "--verbose", action="store_true", dest="verbose",
            default=False, help="Enable verbose mode: "
            "Produces a lot of output, usually helps to identify the "
            "issue root cause if the tool doesn't work as intender.")
        self._parser.add_argument(
            "-d", "--debug", action="store_true", dest="debug",
            default=False, help="R|Enable debug mode (temporaries "
            "will be saved)\n"
            "\\fBUSE WITH CAUTION\\fR: produces lots of files")
        self._parser.add_argument(
            "-l", "--logfile", type=str, action="store", dest="log_file_name",
            help="Log all output to the given file.")
        self._parser.add_argument(
            "-c", "--config", type=str, action="store", dest="config",
            help="Use the custom config file instead of default one.")
        self._parser.add_argument(
            "-j", "--jobs", type=int, action="store", dest="jobs_number",
            help="Number of parallel jobs", default=1)

    def __register_mic_related_options(self):
        """
        Registers the options that are related with MIC options.
        """
        self._parser.add_argument(
            "-A", "--architecture", type=str, action="store",
            help="Specify repo architecture (in OBS/MIC notation)")
        self._parser.add_argument(
            "-k", "--kickstart-file", type=str, action="store",
            dest="kickstart_file", help="Kickstart file used as a template")
        self._parser.add_argument(
            "-o", "--outdir", type=str, action="store", dest="outdir",
            default=".", help="Output directory for MIC.")
        self._parser.add_argument(
            "-C", "--mic-config", type=str, action="store", dest="mic_config",
            default="/etc/mic/mic.conf", help="Default config for MIC.")
        self._parser.add_argument(
            "-M", "--mic-options", action="append", type=str,
            dest="mic_options", help="R|Additional options for MIC."
            "\nDefault option set:"
            "\n"
            "sudo mic create loop <\\fIKICKSTART_FILE\\fR> \\\\"
            "\n  -A <\\fIARCH\\fR> -o <\\fIOUTDIR\\fR> "
            "--tmpfs --pkgmgr=zypp --shrink"
            "\nOptions are appended or override old ones.")

    def __register_special_options(self):
        """
        Registers the options that control specific combirepo behaviour.
        """
        self._parser.add_argument(
            "-m", "--mirror", action="store_true", dest="mirror",
            default=False, help="Take packages from \\fInon-marked\\fR "
            "repository if can't find in marked one. Useful if build in "
            "marked repository could not be completed in full due to "
            "some limitations.")
        self._parser.add_argument(
            "-g", "--greedy", action="store_true", default=False,
            dest="greedy", help="Greedy mode: get as much packages from "
            "\\fImarked\\fR repository as possible, and get rest from "
            "\\fInon-marked\\fR repository. Useful for massive builds: "
            "LTO enabling for whole project, massive sanitizing, compiler "
            "options experiments.")
        self._parser.add_argument(
            "--skip-version-mismatch", action="store_true", default=False,
            dest="skip_mismatch", help="If true and there is version mismatch, "
            "unmark such packages and continue build. Else go to exception in"
            "such case.")
        self._parser.add_argument(
            "-P", "--preferring-strategy", action="store", type=str,
            dest="preferring_strategy", help="Have choice resolving strategy "
            "for the case when there are packages with equal names "
            "but different commit/build numbers. Possible values: "
            "\\fBsmall\\fR (prefer smaller number), "
            "\\fBbig\\fR (prefer bigger number).")
        self._parser.add_argument(
            "-u", "--supplementary-repository-url", action="store", type=str,
            dest="sup_repo_url", help="The URL of "
            "supplementary repository that contains RPMs that are not present "
            "in regular repositories that should be installed to the image. "
            "E.g. for sanitized build this should be a project where "
            "\\fBlibasan\\fR is built.")
        self._parser.add_argument(
            "--user", action="store", type=str, dest="user", help="The user "
            "name at the download server.")
        self._parser.add_argument(
            "--password", action="store", type=str, dest="password",
            help="The password at the download server.")
        self._parser.add_argument(
            "--update-repository", action="append", type=str,
            dest="update_repositories", help="The repository URL that "
            "should be updated. Use word \"all\" to update all repositories")

    def __register_developer_options(self):
        """
        Registers the options that are used not but usual users, by by
        developers.
        """
        self._parser.add_argument(
            "--outdir-preliminary-image", type=str, action="store",
            dest="outdir_original",
            help="\\fBDEBUG\\fR Output directory for MIC (during the "
            "preliminary repository building)")
        self._parser.add_argument(
            "--preliminary-image", type=str, action="store",
            dest="original_image", help="\\fBDEBUG\\fR Don't build "
            "preliminary image, use the specified one for that. "
            "Given argument must be the path to image or images "
            "directory.")
        self._parser.add_argument(
            "--use-custom-qemu", action="store", type=str, dest="qemu_path",
            help="\\fBDEBUG\\fR Path to qemu that should be used. You can "
            "specify the path either to RPM package with qemu or to the "
            "working qemu executable itself.")
        self._parser.add_argument(
            "--tmp-dir", action="store", type=str, dest="cachedir",
            help="Path to cache directory for the tool "
            "(default is /var/tmp/combirepo).")
        self._parser.add_argument(
            "--regenerate-repodata", action="store_true", default=False,
            dest="regenerate_repodata", help="Force repodata regeneration "
            "for repositories.")
        self._parser.add_argument(
            "--disable-rpm-patching", action="store_true", default=False,
            dest="disable_rpm_patching", help="Disable patching of RPM "
            "packages in order to make the build faster.")
        self._parser.add_argument(
            "--drop-patching-cache", action="store_true", default=False,
            dest="drop_patching_cache", help="Drop the cache with patched "
            "RPMs.")
        self._parser.add_argument(
            "--disable-libasan-preloading", action="store_true", default=False,
            dest="disable_libasan_preloading", help="Disable adding "
            "libasan.so.x to /etc/ld.preload at the final stage of build.")

    def __prepare_parser(self):
        """
        Prepares the parser and registers all its options.
        """
        program_description = "COMBIner of RPM REPOsitories."
        self._parser = argparse.ArgumentParser(
            description=program_description,
            formatter_class=self._parser_formatter_class
            )
        self.__register_positional_arguments()
        self.__register_package_name_options()
        self.__register_program_run_options()
        self.__register_mic_related_options()
        self.__register_special_options()
        self.__register_developer_options()

    def __set_program_run_parameters(self, arguments):
        """
        Sets the parameters of the program that controll the program run.

        @param arguments        The parsed arguments.
        """
        if arguments.debug:
            arguments.verbose = True
            temporaries.debug_mode = True
            hidden_subprocess.visible_mode = True
        if arguments.verbose:
            logging_level = logging.DEBUG
            hidden_subprocess.visible_mode = True
        else:
            logging_level = logging.INFO

        if arguments.log_file_name and len(arguments.log_file_name) > 0:
            log_file_name = arguments.log_file_name
        elif not arguments.verbose:
            log_file_name = "combirepo.{0}.log".format(os.getpid())
        else:
            log_file_name = None
        if log_file_name is not None:
            logging.basicConfig(level=logging_level,
                                filename=log_file_name)
            atexit.register(sys.stdout.write, "The log with additional info "
                            "was saved to {0}\n".format(log_file_name))
        else:
            logging.basicConfig(level=logging_level)

        if len(arguments.triplets) == 0:
            gen_init_config = True
        else:
            gen_init_config = False

        config_parser.initialize_config(arguments.config, gen_init_config)
        repository_combiner.jobs_number = arguments.jobs_number

    def __build_repository_pairs(self, arguments):
        """
        Processes the positional arguments and builds repository pairs from
        them.

        @param arguments        The parsed arguments.
        @return                 The list of repository pairs.
        """
        if len(arguments.triplets) == 0:
            logging.debug("Repository info will be read from config file...")
            return []
        if len(arguments.triplets) % 3 != 0:
            logging.error("Number of positional arguments should be divided "
                          "by 3")
            sys.exit("Error.")

        logging.debug("Triplets before parsing: "
                      "{0}".format(arguments.triplets))
        triplets = convert_list_to_sequential_tuples(arguments.triplets, 3)
        logging.debug("Triplets after parsing: "
                      "{0}".format(arguments.triplets))
        repository_pairs = []
        for triplet in triplets:
            repository_pair = RepositoryPair()
            repository_pair.name = triplet[0]
            logging.debug("triplet[1] = {0}".format(triplet[1]))
            repository_pair.url = triplet[1]
            repository_pair.url_marked = triplet[2]
            repository_pairs.append(repository_pair)
        return repository_pairs

    def __parse_packages_file(self, packages_file):
        packages_list = []
        if packages_file is not None:
            with open(packages_file, 'r') as pkg_file:
                for package in pkg_file:
                    packages_list.append(package.strip())
        return packages_list

    def __build_package_names(self, arguments):
        """
        Processes parsed package-related options and builds package names from
        them.

        @param arguments        The parsed arguments.
        @return                 The dictionary of package names.
        """
        package_names = {}
        package_names["forward"] = split_names_list(arguments.forward)
        package_names["backward"] = split_names_list(arguments.backward)
        package_names["single"] = split_names_list(arguments.single)
        package_names["excluded"] = split_names_list(arguments.exclude)
        package_names["service"] = split_names_list(arguments.service)
        package_names["preferable"] = split_names_list(arguments.preferable)
        return package_names

    def parse(self):
        """
        Parses the command-line arguments of the script, sets the program run
        mode based on it, and builds the parameters structure for the
        repository combiner.

        @return         The combirepo parameters.
        """
        self.__prepare_parser()
        arguments = self._parser.parse_args()
        self.__set_program_run_parameters(arguments)

        parameters = RepositoryCombinerParameters()
        parameters.profile_name = "commandline"
        repository_pairs = self.__build_repository_pairs(arguments)
        parameters.repository_pairs = repository_pairs
        if arguments.packages_file is not None:
            parameters.packages_list = self.__parse_packages_file(arguments.packages_file)

        # Process MIC-related options:
        if arguments.architecture is not None:
            parameters.architecture = arguments.architecture
        if arguments.kickstart_file is not None:
            parameters.kickstart_file_path = arguments.kickstart_file
        if arguments.outdir is not None:
            parameters.output_directory_path = arguments.outdir
        if arguments.mic_config is not None:
            parameters.mic_config = arguments.mic_config
        if arguments.mic_options is not None:
            splitted_options = []
            for option in arguments.mic_options:
                splitted_options.extend(re.split("[\ \n\t]", option))
            parameters.mic_options = splitted_options

        package_names = self.__build_package_names(arguments)
        parameters.package_names = package_names

        parameters.greedy_mode = arguments.greedy
        parameters.mirror_mode = arguments.mirror
        parameters.skip_mismatch = arguments.skip_mismatch
        parameters.disable_rpm_patching = arguments.disable_rpm_patching
        if arguments.preferring_strategy is not None:
            parameters.preferring_strategy = arguments.preferring_strategy
        if arguments.sup_repo_url is not None:
            parameters.sup_repo_url = arguments.sup_repo_url
        if arguments.user is not None:
            parameters.user = arguments.user
        if arguments.password is not None:
            parameters.password = arguments.password
        if arguments.update_repositories is not None:
            url = arguments.update_repositories
            repository_manager.update_repositories = url

        if arguments.cachedir is not None:
            parameters.temporary_directory_path = arguments.cachedir

        # Process developer options related with RPM patcher:
        rpm_patcher.developer_outdir_original = arguments.outdir_original
        rpm_patcher.developer_original_image = arguments.original_image
        rpm_patcher.developer_qemu_path = arguments.qemu_path
        if arguments.disable_rpm_patching:
            rpm_patcher.developer_disable_patching = True
            atexit.register(logging.warning, "Be careful, RPM patching was "
                            "disabled!")
        rpm_patcher.drop_patching_cache = arguments.drop_patching_cache
        if arguments.disable_libasan_preloading:
            repository_combiner.libasan_preloading = False

        if_regenerate = arguments.regenerate_repodata
        repository_combiner.repodata_regeneration_enabled = if_regenerate

        return parameters


def parser_options(formatter_class=argparse.HelpFormatter):
    """
    Retrieve a customized parser to generate man page
    """
    return CommandlineParser().get_formatted_parser(formatter_class)
