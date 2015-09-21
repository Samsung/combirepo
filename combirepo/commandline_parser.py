#!/usr/bin/env python2.7
# -*- coding: utf-8 -*-
import os
import shutil
import argparse
import sys
import logging
import temporaries
import hidden_subprocess
from strings import split_names_list
from parameters import RepositoryCombinerParameters
import rpm_patcher
import config_parser
from repository_pair import RepositoryPair
import repository_combiner


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
        Initializes the parser (does nothing).
        """
        self._parser = None

    def __register_positional_arguments(self):
        """
        Register positional arguments.
        """
        self._parser.add_argument("triplets", type=str, nargs='*',
                                  help="Triplets: 1. Name of "
                                  "repository as specified in kickstart file, "
                                  "2. Path to non-marked repository, "
                                  "3. Path to marked repository.")

    def __register_package_name_options(self):
        """
        Registers options that controll package name handling.
        """
        self._parser.add_argument("-f", "--forward", type=str, action="append",
                                  help="The name of package that should be "
                                  "marked with all its forward dependencies")
        self._parser.add_argument("-b", "--backward", type=str,
                                  action="append",
                                  help="The name of package that should be "
                                  "marked with all its backward dependencies "
                                  "(i. e. dependees)")
        self._parser.add_argument("-s", "--single", type=str, action="append",
                                  help="The name of package that should be "
                                  "marked")
        self._parser.add_argument("-e", "--exclude", type=str, action="append",
                                  help="The name of package that should be "
                                  "excluded from the final list of marked "
                                  "packages.")
        self._parser.add_argument("-S", "--service", type=str,
                                  action="append", help="The name of "
                                  "package that are not installed to the "
                                  "image by default, but that must be "
                                  "installed in this build.")
        self._parser.add_argument("-p", "--preferable", action="append",
                                  type=str, dest="preferable",
                                  help="The name of package that should "
                                  "be prefered in case of \"have choice\" "
                                  "problem.")

    def __register_program_run_options(self):
        """
        Registers the options that controll the program run.
        """
        self._parser.add_argument("-v", "--verbose", action="store_true",
                                  dest="verbose", default=False,
                                  help="Enable verbose mode")
        self._parser.add_argument("-d", "--debug", action="store_true",
                                  dest="debug", default=False,
                                  help="Enable debug mode (temporaries "
                                  "will be saved)")
        self._parser.add_argument("-l", "--logfile", type=str, action="store",
                                  dest="log_file_name", help="Log all output "
                                  "to the given file.")
        self._parser.add_argument("-c", "--config", type=str, action="store",
                                  dest="config", default="~/.combirepo.conf",
                                  help="Use the custom config file instead of "
                                  "default one.")

    def __register_mic_related_options(self):
        """
        Registers the options that are related with MIC options.
        """
        self._parser.add_argument("-A", "--architecture", type=str,
                                  action="store",
                                  help="Specify repo architecture "
                                  "(as for MIC tool)")
        self._parser.add_argument("-k", "--kickstart-file", type=str,
                                  action="store", dest="kickstart_file",
                                  help="Kickstart file used as a template")
        self._parser.add_argument("-o", "--outdir", type=str, action="store",
                                  dest="outdir", default=".",
                                  help="Output directory for MIC.")
        self._parser.add_argument("-M", "--mic-options", action="append",
                                  type=str, dest="mic_options",
                                  help="Additional options for MIC."
                                  "\nBy default the following options are set:"
                                  "\n \""
                                  "sudo mic create loop <YOUR KICKSTART FILE> "
                                  "\n -A <THE SPECIFIED ARCHITECTURE> "
                                  "\n -o <THE SPECIFIED OUTPUT DIRECTORY>"
                                  "\n --tmpfs \n --pkgmgr=zypp \n --shrink\""
                                  "\n     . You can append options to add "
                                  "new or change old ones.")

    def __register_special_options(self):
        """
        Registers the options that control specific combirepo behaviour.
        """
        self._parser.add_argument("-m", "--mirror", action="store_true",
                                  dest="mirror", default=False,
                                  help="Whether to mirror"
                                  " not found marked packages from non-marked "
                                  "repository")
        self._parser.add_argument("-g", "--greedy", action="store_true",
                                  default=False, dest="greedy",
                                  help="Greedy mode: get"
                                  " as much packages from marked repository "
                                  "as possible, and get others from "
                                  "non-marked repository.")
        self._parser.add_argument("-P", "--preferring-strategy",
                                  action="store",
                                  type=str, dest="prefer_strategy",
                                  help="Have choice "
                                  "resolving strategy for the case when there "
                                  "are packages with equal names but "
                                  "different commit/build numbers. Possible "
                                  "values: small (prefer smaller), "
                                  "big (prefer bigger).")
        self._parser.add_argument("-u", "--supplementary-repository-url",
                                  action="store", type=str,
                                  dest="repository_supplementary_url",
                                  help="The URL of supplementary repository "
                                  "that contains RPMs that are not present "
                                  "in regular repositories that should be "
                                  "installed to the image.")

    def __register_developer_options(self):
        """
        Registers the options that are used not but usual users, by by
        developers.
        """
        self._parser.add_argument("--outdir-preliminary-image", type=str,
                                  action="store", dest="outdir_original",
                                  default="./.preliminary-image",
                                  help="Output directory for "
                                  "MIC (during the preliminary repository "
                                  "building)")
        self._parser.add_argument("--preliminary-image", type=str,
                                  action="store", dest="original_image",
                                  help="Don't build preliminary "
                                  "image, use the specified one for that. "
                                  "Given argument must be the path to image "
                                  "or images directory.")
        self._parser.add_argument("--use-custom-qemu", action="store",
                                  type=str, dest="qemu_path",
                                  help="Path to qemu that should be "
                                  "used. You can specify the path either "
                                  "to RPM package with qemu or to the "
                                  "working qemu executable itself.")
        self._parser.add_argument("--cachedir", action="store", type=str,
                                  dest="cachedir",
                                  default="/var/tmp/combirepo",
                                  help="The path to the directory where "
                                  "combirepo saves its cache.")
        self._parser.add_argument("--regenerate-repodata",
                                  action="store_true",
                                  default=False, dest="regenerate_repodata",
                                  help="Whether to re-generate the "
                                  "repodata for specified repositories")

    def __prepare_parser(self):
        """
        Prepares the parser and registers all its options.
        """
        program_description = "COMBIner of RPM REPOsitories."
        self._parser = argparse.ArgumentParser(description=program_description)
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

        if arguments.log_file_name:
            logging.basicConfig(level=logging_level,
                                filename=arguments.log_file_name)
        else:
            logging.basicConfig(level=logging_level)

        config_parser.default_path = os.path.expanduser(arguments.config)

    def __build_repository_pairs(self, arguments):
        """
        Processes the positional arguments and builds repository pairs from
        them.

        @param arguments        The parsed arguments.
        @return                 The list of repository pairs.
        """
        if len(arguments.triplets) == 0:
            logging.info("Repository info will be read from config file...")
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

        # Process MIC-related options:
        if arguments.architecture is not None:
            parameters.architecture = arguments.architecture
        if arguments.kickstart_file is not None:
            parameters.kickstart_file_path = arguments.kickstart_file
        if arguments.outdir is not None:
            parameters.output_directory_path = arguments.outdir
        if arguments.mic_options is not None:
            splitted_options = []
            for option in arguments.mic_options:
                splitted_options.extend(re.split("[\ \n\t]", option))
            parameters.mic_options = splitted_options

        package_names = self.__build_package_names(arguments)
        parameters.package_names = package_names

        parameters.greedy_mode = arguments.greedy
        parameters.mirror_mode = arguments.mirror
        if arguments.prefer_strategy is not None:
            parameters.prefer_strategy = arguments.prefer_strategy
        supplementary_url = arguments.repository_supplementary_url
        parameters.repository_supplementary_url = supplementary_url

        parameters.temporary_directory_path = arguments.cachedir
        directory = os.path.join(arguments.cachedir, "temporaries")
        temporaries.default_directory = os.path.abspath(directory)
        if not os.path.isdir(temporaries.default_directory):
            os.mkdir(temporaries.default_directory)

        # Process developer options related with RPM patcher:
        rpm_patcher.developer_outdir_original = arguments.outdir_original
        rpm_patcher.developer_original_image = arguments.original_image
        rpm_patcher.developer_qemu_path = arguments.qemu_path

        repository_combiner.regenerate_repodata = arguments.regenerate_repodata

        return parameters
