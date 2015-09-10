#!/usr/bin/env python2.7
# -*- coding: utf-8 -*-
import os
import sys
import logging


binfmt_directory = "/proc/sys/fs/binfmt_misc"


def get_name(architecture):
    """
    Gets the name of binfmt file by the architecture.

    @param architecture The architecture.
    @return             The binafmt name.
    """
    binfmt_name = None
    if "arm64" in architecture or "aarch64" in architecture:
        binfmt_name = "arm64"
    elif "arm" in architecture:
        binfmt_name = "arm"
    else:
        raise Exception("Behavior for architecture {0} is not "
                        "implemented!".format(architecture))
    return binfmt_name


def disable_all():
    """
    Disables or registered binary formats
    """
    binfmt_status_path = os.path.join(binfmt_directory, "status")
    if not os.path.isfile(binfmt_status_path):
        logging.error("binfmt status file does not exit!")
        sys.exit("Error.")

    if os.path.isfile(binfmt_status_path):
        with open(binfmt_status_path, 'w') as binfmt_status:
            binfmt_status.write("-1\n")


binfmt_magic = {}
binfmt_mask = {}
binfmt_flag = {}
binfmt_magic["arm"] = "".join(["\\x7fELF",
                               "\\x01", "\\x01", "\\x01", "\\x00",
                               "\\x00", "\\x00", "\\x00", "\\x00",
                               "\\x00", "\\x00", "\\x00", "\\x00",
                               "\\x02", "\\x00", "\\x28", "\\x00"])
binfmt_mask["arm"] = "".join(["\\xff", "\\xff", "\\xff", "\\xff",
                              "\\xff", "\\xff", "\\xff", "\\x00",
                              "\\xff", "\\xff", "\\xff", "\\xff",
                              "\\xff", "\\xff", "\\xff", "\\xff",
                              "\\xfe", "\\xff", "\\xff", "\\xff"])
binfmt_magic["arm64"] = "".join(["\\x7fELF",
                                 "\\x02", "\\x01", "\\x01", "\\x00",
                                 "\\x00", "\\x00", "\\x00", "\\x00",
                                 "\\x00", "\\x00", "\\x00", "\\x00",
                                 "\\x02", "\\x00", "\\xb7"])
binfmt_mask["arm64"] = "".join(["\\xff", "\\xff", "\\xff", "\\xff",
                                "\\xff", "\\xff", "\\xff", "\\x00",
                                "\\xff", "\\xff", "\\xff", "\\xff",
                                "\\xff", "\\xff", "\\xff", "\\xff",
                                "\\xfe", "\\xff", "\\xff"])
binfmt_flag["qemu"] = "OC"
binfmt_flag["qemu-wrapper"] = "P"


def register(architecture, qemu_executable_path):
    """
    Register the binary format for the given architecture.

    @param architecture         The architecture.
    @param qemu_executable_path The absolute path to qemu binary INSIDE the
                                chroot directory (after chrooting to it). It
                                must always begin with '/'.
    """
    qemu_type = "qemu"
    if os.path.basename(qemu_executable_path).endswith("-binfmt"):
        qemu_type = "qemu-wrapper"
    binfmt_register_path = os.path.join(binfmt_directory, "register")
    if not os.path.isfile(binfmt_register_path):
        logging.error("binfmt register file does not exist!")
        sys.exit("Error.")

    binfmt_name = get_name(architecture)
    binary_format = ":{0}:M::{1}:{2}:{3}:{4}".format(binfmt_name,
                                                     binfmt_magic[binfmt_name],
                                                     binfmt_mask[binfmt_name],
                                                     qemu_executable_path,
                                                     binfmt_flag[qemu_type])
    with open(binfmt_register_path, 'w') as binfmt_register:
        binfmt_register.write(binary_format)
