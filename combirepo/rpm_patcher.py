#!/usr/bin/env python2.7
# -*- coding: utf-8 -*-
import os
import sys
import platform
import shutil
import multiprocessing
import subprocess
import temporaries
import logging
import re
from sets import Set
import files
import check
import hidden_subprocess
import binfmt
from kickstart_parser import KickstartFile
import repository_combiner


developer_outdir_original = None
developer_original_image = None
developer_qemu_path = None
developer_disable_patching = False


def prepare_minimal_packages_list(graphs):
    """
    Prepares the minimal list of package names that are needed to be installed
    in the chroot so that rpmrebuild can be used inside it.

    @param graphs           The list of dependency graphs of repositories.
    @return                 The list of packages.
    """
    symbols = ["useradd", "mkdir", "awk", "cpio", "make", "rpmbuild", "sed"]
    deprecated_substrings = ["mic-bootstrap", "x86", "x64"]
    providers = {}
    for symbol in symbols:
        for graph in graphs:
            if providers.get(symbol) is None:
                providers[symbol] = Set()
            names = graph.get_provider_names(symbol)
            if names is not None:
                providers[symbol] = providers[symbol] | Set(names)
                logging.debug("Got providers {0} for symbol "
                              "{1}".format(names, symbol))
                logging.debug("{0}".format(providers[symbol]))

    packages = []
    for symbol in symbols:
        provider = None
        if len(providers[symbol]) < 1:
            for graph in graphs:
                for key in graph.symbol_providers.keys():
                    logging.debug("{0} : {1}".format(
                        key, graph.symbol_providers[key]))
            logging.error("Failed to find symbol {0}".format(symbol))
            logging.error("size: {0}".format(len(graph.symbol_providers)))
            sys.exit("Error.")
        elif len(providers[symbol]) > 1:
            logging.debug("Analyzing symbol {0}:".format(symbol))
            for provider in providers[symbol]:
                logging.debug(" Provided by {0}".format(provider))
                for substring in deprecated_substrings:
                    if substring in provider:
                        logging.debug("   ^--- will be ignored, contains "
                                      "{0}".format(substring))
                        providers[symbol] = providers[symbol] - Set([provider])
                        logging.debug("      {0}".format(providers[symbol]))
            if len(providers[symbol]) > 1:
                logging.warning("Multiple provider names for symbol "
                                "\"{0}\":".format(symbol))
                for provider in providers[symbol]:
                    logging.warning(" * {0}".format(provider))

            provider = next(iter(providers[symbol]))  # FIXME: is it correct?
        else:
            provider = next(iter(providers[symbol]))
        packages.append(provider)

    logging.debug("Minimal packages list:")
    for package in packages:
        logging.debug(" * {0}".format(package))

    return packages


def rebuild_rpm_package(package_name, release):
    """
    Rebuilds the RPM package so that to adjust it release number.

    @param package_name     The path to the package.
    @param release          The required release number.
    @return                 The name of patched package.
    """

    rpmrebuild_command = ["rpmrebuild",
                          "--release={0}".format(release), "-p", "-n",
                          package_name]
    logging.info("Running command: "
                 "{0}".format(" ".join(rpmrebuild_command)))
    log_file_name = temporaries.create_temporary_file("rpmrebuild.log")
    with open(log_file_name, 'w') as log_file:
        code = subprocess.call(rpmrebuild_command, stdout=log_file,
                               stderr=log_file)
    if code != 0:
        logging.error("The subprocess failed!")
        logging.error("STDERR output:")
        with open(log_file_name, 'r') as log_file:
            logging.error("{0}".format(log_file.read()))

    result = None
    with open(log_file_name, 'r') as log_file:
        for line in log_file:
            if line.startswith("result: "):
                result = line.replace("result: ", "")
                result = result.replace("\n", "")
    if result is None:
        logging.error("Failed to patch RPM file!")
        sys.exit("Error.")
    return result


class RpmPatcher():
    """
    The object of this class is used to patch RPMs so that to make them
    possible to be installed in the combined image.
    """
    def __init__(self, names, repositories, architecture, kickstart_file_path,
                 graphs):
        """
        Initializes the RPM patcher (does nothing).

        @param names                The list of repository names.
        @param repositories         The list of repositories.
        @param architecture         The architecture of the image.
        @param kickstart_file_path  The path to the working kickstart file.
        """
        self.images_directory = None
        self.names = names
        self.repositories = repositories
        self.architecture = architecture
        self.kickstart_file_path = kickstart_file_path
        global developer_qemu_path
        self.qemu_path = developer_qemu_path
        self.patching_root = None
        self._tasks = []
        self._graphs = graphs

    def __find_platform_images(self):
        """
        Finds the platform images in the directory.

        @return                     The path to the selected images.
        """
        logging.debug("Searching in directory "
                      "{0}".format(self.images_directory))
        if not os.path.isdir(self.images_directory):
            raise Exception("{0} is not a "
                            "directory!".format(self.images_directory))
        images = files.find_fast(self.images_directory, ".*\.img$")

        return images

    def __mount_images_triplet(self, images, directory):
        """
        Mounts the images (rootfs + system-data + user) to the given
        directory.

        @param images       The list of paths to images.
        @param directory    The mount directory.
        """
        for image in images:
            if os.path.basename(image) == "rootfs.img":
                rootfs_image = image
            elif os.path.basename(image) == "system-data.img":
                system_image = image
            elif os.path.basename(image) == "user.img":
                user_image = image
            else:
                raise Exception("Unknown image name!")

        temporaries.mount_image(directory, rootfs_image)
        system_directory = os.path.join(os.path.join(directory, "opt"))
        if not os.path.isdir(system_directory):
            os.mkdir(system_directory)
        temporaries.mount_image(system_directory, system_image)
        user_directory = os.path.join(system_directory, "usr")
        if not os.path.isdir(user_directory):
            os.mkdir(user_directory)
        temporaries.mount_image(user_directory, user_image)

    def __produce_architecture_synonyms_list(self, architecture):
        """
        Produces the list of architecture names that are synonyms or
        compatible.

        @param architecture The architecture.
        @return             The list of compatible architectures.
        """
        if "arm64" in architecture or "aarch64" in architecture:
            return ["aarch64", "arm64", architecture]
        if "arm" in architecture:
            return ["arm", architecture]
        if "x86_64" in architecture or "86" in architecture:
            return ["x86_64", "x86", architecture]

    def __process_user_qemu_executable(self):
        """
        Processes the qemu executable specified by user, checks it and in
        case of success copies it to the directory.
        """
        qemu_executable_path = None
        if os.path.isfile(self.qemu_path):
            # FIXME: Here should be file type checking.
            if not os.path.basename(self.qemu_path).endswith(".rpm"):
                logging.info("Checking specified qemu executable "
                             "{0}...".format(self.qemu_path))
                if not check.command_exists(self.qemu_path):
                    logging.error("The specified qemu executable is not "
                                  "working.")
                    sys.exit("Error.")
                else:
                    install_directory = os.path.join(self.patching_root,
                                                     "usr/local/bin")
                    if not os.path.isdir(install_directory):
                        os.makedirs(os.path.join(install_directory))
                    qemu_name = os.path.basename(self.qemu_path)
                    install_path = os.path.join(install_directory, qemu_name)
                    shutil.copy(self.qemu_path, install_path)
                    relative_path = os.path.relpath(install_path,
                                                    self.patching_root)
                    qemu_executable_path = "/{0}".format(relative_path)

        else:
            logging.error("Specified file {0} does not exist or is not a "
                          "file!".format(qemu_path))
            sys.exit("Error.")
        return qemu_executable_path

    def __unpack_qemu_packages(self):
        """
        Looks for all qemu packages in the given list of repositories and
        unpacks them to the given directory.
        """
        initial_directory = os.getcwd()
        qemu_packages = []

        qemu_package = self.qemu_path
        if qemu_package is None:
            expression = "^qemu.*\.{0}\.rpm$".format(self.architecture)
            for repository in self.repositories:
                qemu_packages_portion = files.find_fast(repository, expression)
                qemu_packages.extend(qemu_packages_portion)
            logging.warning("The following qemu packages will be unpacked in "
                            "chroot:")
            for package in qemu_packages:
                logging.warning(" * {0}".format(package))
        else:
            qemu_packages.append(qemu_package)

        for package in qemu_packages:
            files.unrpm(package, self.patching_root)

    def __find_qemu_executable(self):
        """
        Looks for the appropriate qemu executable for the given architecture
        in the given directory.
        """

        # The synonyms for the architecture:
        arches = self.__produce_architecture_synonyms_list(self.architecture)
        executables = []
        for arch in arches:
            qemu_name = "^qemu-{0}$".format(arch)
            qemu_binfmt_name = "^qemu-{0}-binfmt$".format(arch)
            executables_portion = files.find_fast(self.patching_root,
                                                  qemu_binfmt_name)
            executables.extend(executables_portion)
            executables_portion = files.find_fast(self.patching_root,
                                                  qemu_name)
            executables.extend(executables_portion)

        logging.warning("Found several qemu executables:")
        working_executables = []
        for path in executables:
            relative_path = os.path.relpath(path, self.patching_root)
            if check.command_exists(path):
                working_executables.append(path)
                summary = "workinig"
            else:
                summary = "not working"
            logging.warning(" * /{0} ({1})".format(relative_path, summary))

        if len(working_executables) < 1:
            logging.error("No working qemu executables found!")
            sys.exit("Error.")
        else:
            selected_path = working_executables[0]

        relative_path = os.path.relpath(selected_path, self.patching_root)
        logging.warning("The following one was selected: "
                        "/{0}".format(relative_path))
        return "/{0}".format(relative_path)

    def __deploy_qemu_package(self):
        """
        Deploys all qemu packages that can be found in the specified list of
        repositories and that have the specified architecture in the given
        directory.
        """
        qemu_executable_path = None
        if self.qemu_path is not None:
            qemu_executable_path = self.__process_user_qemu_executable()

        if qemu_executable_path is None:
            self.__unpack_qemu_packages()
            qemu_executable_path = self.__find_qemu_executable()

        binfmt.disable_all()
        binfmt.register(self.architecture, qemu_executable_path)

    def __install_rpmrebuild(self, queue):
        """
        Chroots to the given path and installs rpmrebuild in it.

        @param queue    The queue where the result will be put.
        """
        os.chroot(self.patching_root)
        os.chdir("/")
        os.chdir("/rpmrebuild/src")
        hidden_subprocess.call("Making the rpmrebuild.", ["make"])
        hidden_subprocess.call("Installing the rpmrebuild.",
                               ["make", "install"])
        if not check.command_exists("rpmrebuild"):
            sys.exit("Error.")
        queue.put(True)

    def __prepare(self):
        """
        Prepares the patching root ready for RPM patching.

        """
        global developer_disable_patching
        if developer_disable_patching:
            logging.debug("RPM patcher will not be prepared.")
            return
        graphs = self._graphs
        self.__prepare_image(graphs)
        images = self.__find_platform_images()
        if len(images) == 0:
            logging.error("No images were found.")
            sys.exit("Error.")
        self.patching_root = temporaries.create_temporary_directory("root")

        # For all-in-one images:
        if len(images) == 1:
            image = images[0]
            temporaries.mount_image(self.patching_root, image)
        # For 3-parts images:
        elif len(images) == 3:
            self.__mount_images_triplet(images, self.patching_root)
        else:
            raise Exception("This script is able to handle only all-in-one or "
                            "three-parted images!")

        host_arch = platform.machine()
        host_arches = self.__produce_architecture_synonyms_list(host_arch)
        if self.architecture not in host_arches:
            self.__deploy_qemu_package()

        combirepo_dir = os.path.abspath(os.path.dirname(__file__))
        rpmrebuild_file = os.path.join(combirepo_dir, 'data/rpmrebuild.tar')
        already_present_rpmrebuilds = files.find_fast(self.patching_root,
                                                      "rpmrebuild.*")
        for already_present_rpmrebuild in already_present_rpmrebuilds:
            if os.path.isdir(already_present_rpmrebuild):
                shutil.rmtree(already_present_rpmrebuild)
            elif os.path.isfile(already_present_rpmrebuild):
                os.remove(already_present_rpmrebuild)
        hidden_subprocess.call("Extracting the rpmrebuild ",
                               ["tar", "xf", rpmrebuild_file, "-C",
                                self.patching_root])

        queue = multiprocessing.Queue()
        child = multiprocessing.Process(target=self.__install_rpmrebuild,
                                        args=(queue,))
        child.start()
        child.join()
        if queue.empty():
            logging.error("Failed to install rpmrebuild into chroot.")
            sys.exit("Error.")
        else:
            result = queue.get()
            if result:
                logging.debug("Installation of rpmrebuild successfully "
                              "completed.")
            else:
                raise Exception("Impossible happened.")

    def __create_patched_package(self, queue, package_name, release):
        """
        Patches the given package using rpmrebuild and the patching root.

        @param queue            The queue used for saving the resulting file
                                name.
        @param package_name     The basename of the package.
        @param release          The release number of the corresponding
                                non-marked package.
        """
        logging.debug("Chrooting to the directory "
                      "{0}".format(self.patching_root))
        os.chroot(self.patching_root)
        os.chdir("/")
        check.file_exists(package_name)
        comment = "Patching package {0}".format(os.path.basename(package_name))
        result = hidden_subprocess.function_call(comment, rebuild_rpm_package,
                                                 package_name, release)
        queue.put(result)

    def add_task(self, package_path, directory, release):
        """
        Adds a task to the RPM patcher.

        @param package_path     The path to the marked package.
        @param directory        The destination directory where to save the
                                package copy.
        @param release          The release number of the corresponding
                                non-marked package.
        """
        self._tasks.append((package_path, directory, release))

    def do_tasks(self):
        """
        Creates copies of added packages in the given directories and adjusts
        their release numbers to the given values.
        """
        self.__prepare()
        for task in self._tasks:
            package_path, directory, release = task
            check.file_exists(package_path)
            global developer_disable_patching
            if developer_disable_patching:
                shutil.copy(package_path, directory)
                continue

            shutil.copy(package_path, self.patching_root)
            package_name = os.path.basename(package_path)

            queue = multiprocessing.Queue()
            child = multiprocessing.Process(
                target=self.__create_patched_package,
                args=(queue, package_name, release,))
            child.start()
            child.join()
            patched_package_name = os.path.basename(queue.get())
            logging.info("The package has been rebuilt to adjust release "
                         "numbers: {0}".format(patched_package_name))
            expression = re.escape(patched_package_name)
            patched_package_paths = files.find_fast(self.patching_root,
                                                    expression)
            patched_package_path = None
            if len(patched_package_paths) < 1:
                raise Exception("Failed to find file "
                                "{0}".format(patched_package_name))
            elif len(patched_package_paths) > 1:
                raise Exception("Found multiple files "
                                "{0}".format(patched_package_name))
            else:
                patched_package_path = patched_package_paths[0]
            shutil.copy(patched_package_path, directory)

    def __prepare_image(self, graphs):
        """
        Prepares the image needed for the RPM patcher.

        @param graphs           The list of dependency graphs of repositories.
        @return                 The directory with preliminary images.
        """
        original_images_dir = None
        global developer_original_image
        global developer_outdir_original
        self.images_directory = developer_outdir_original
        if not os.path.isdir(developer_outdir_original):
            os.makedirs(developer_outdir_original)
        if (self.__find_platform_images() is not None and
                len(self.__find_platform_images()) > 0):
            return

        if developer_original_image is None:
            if developer_outdir_original is None:
                directory = temporaries.create_temporary_directory("orig")
                developer_outdir_original = directory
            original_images_dir = developer_outdir_original
            path = temporaries.create_temporary_file("mod.ks")
            shutil.copy(self.kickstart_file_path, path)
            kickstart_file = KickstartFile(path)
            kickstart_file.comment_all_groups()
            logging.debug("Repositories: {0}".format(self.repositories))
            packages = prepare_minimal_packages_list(graphs)
            repository_combiner.create_image(self.architecture, self.names,
                                             self.repositories,
                                             path, original_images_dir,
                                             [], packages)
        else:
            if os.path.isdir(developer_original_image):
                original_images_dir = developer_original_image
            elif os.path.isfile(developer_original_image):
                original_images_dir = os.path.dirname(developer_original_image)
            else:
                logging.error("Given {0} is not a file or a "
                              "directory.".format(developer_original_image))
                sys.exit("Error.")
        self.images_directory = original_images_dir
