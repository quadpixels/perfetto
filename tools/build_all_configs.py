#!/usr/bin/env python3
# Copyright (C) 2017 The Android Open Source Project
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import argparse
import os
import platform
import subprocess
import sys
import re

from compat import iteritems, quote

MAC_BUILD_CONFIGS = {
    'mac_debug': ('is_clang=true', 'is_debug=true'),
    'mac_release': ('is_clang=true', 'is_debug=false'),
    'mac_asan': ('is_clang=true', 'is_debug=false', 'is_asan=true'),
    'mac_tsan': ('is_clang=true', 'is_debug=false', 'is_tsan=true'),
    'mac_ubsan': ('is_clang=true', 'is_debug=false', 'is_ubsan=true'),
}

ANDROID_BUILD_CONFIGS = {
    'android_debug': ('target_os="android"', 'is_clang=true', 'is_debug=true'),
    'android_release':
        ('target_os="android"', 'is_clang=true', 'is_debug=false'),
    'android_release_incl_heapprofd':
        ('target_os="android"', 'is_clang=true', 'is_debug=false',
         'extra_cflags="-funwind-tables"', 'android_api_level=29'),
    'android_asan': ('target_os="android"', 'is_clang=true', 'is_debug=false',
                     'is_asan=true'),
    'android_lsan': ('target_os="android"', 'is_clang=true', 'is_debug=false',
                     'is_lsan=true'),
}

ANDROID_ARCHS = ('arm', 'arm64')

LINUX_BUILD_CONFIGS = {
    'linux_gcc_debug': ('is_clang=false', 'is_debug=true'),
    'linux_gcc_release': ('is_clang=false', 'is_debug=false'),
    'linux_clang_debug': ('is_clang=true', 'is_debug=true'),
    'linux_clang_release': ('is_clang=true', 'is_debug=false'),
    'linux_asan': ('is_clang=true', 'is_debug=false', 'is_asan=true'),
    'linux_lsan': ('is_clang=true', 'is_debug=false', 'is_lsan=true'),
    'linux_msan': ('is_clang=true', 'is_debug=false', 'is_msan=true'),
    'linux_tsan': ('is_clang=true', 'is_debug=false', 'is_tsan=true'),
    'linux_ubsan': ('is_clang=true', 'is_debug=false', 'is_ubsan=true'),
    'linux_fuzzer': ('is_clang=true', 'is_debug=false', 'is_fuzzer=true',
                     'is_asan=true'),
}

LINUX_ARCHS = ('arm', 'arm64',)

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

OPENBMC_BUILD_CONFIGS = {
    'openbmc_gcc_debug':   ('is_clang=false', 'is_debug=true' ),
    'openbmc_gcc_release': ('is_clang=false', 'is_debug=false'),
}

OPENBMC_ARCHS = ('arm',)

def GetOpenBMCVariables(sdkpath):
  ret = {}
  maybe_sr = os.path.join(sdkpath, "sysroots")
  if os.path.exists(maybe_sr):
    for p in os.listdir(maybe_sr):
      if p.endswith("gnueabi"):
        ret["sysroot"] = os.path.join(maybe_sr, p)
  filenames = [os.path.join(dp, f) for dp, dn, fn in \
    os.walk(os.path.expanduser(sdkpath)) for f in fn]
  for fn in filenames:
    fn = fn.strip()
    if fn.endswith("gnueabi-g++"):
      ret["g++"] = fn
    elif fn.endswith("gnueabi-gcc-ar"):
      ret["ar"] = fn
    elif fn.endswith("gnueabi-gcc"):
      ret["gcc"] = fn
    elif fn.endswith("gnueabi-strip"):
      ret["strip"] = fn
  return ret

def ProcessOpenBMCToolchainNinjaFile(file_path, openbmc_vars):
  with open(file_path) as f:
    lines = f.readlines()
    for i in range(len(lines)):
      lines[i] = re.sub("--sysroot=[\S]+",
                        "--sysroot=" + openbmc_vars["sysroot"],
                        lines[i])
      lines[i] = lines[i].replace("arm-linux-gnueabihf-g++",
                                  openbmc_vars["g++"])
      lines[i] = lines[i].replace("arm-linux-gnueabihf-gcc",
                                  openbmc_vars["gcc"])
      lines[i] = lines[i].replace("arm-linux-gnueabihf-ar",
                                  openbmc_vars["ar"])
      lines[i] = lines[i].replace(" strip ",
                                  " " + openbmc_vars["strip"] + " ")
  with open(file_path, 'w') as f:
    for line in lines:
      f.write(line)

def RemoveICFAllFlag(out_dir):
  filenames = [os.path.join(dp, f) for dp, dn, fn in \
    os.walk(os.path.expanduser(out_dir)) for f in fn]
  for fn in filenames:
    if fn.endswith(".ninja"):
      with open(fn) as f:
        lines = f.readlines()
      replaced = False
      for i in range(len(lines)):
        for x in ["-Wl,--icf=all", "-Werror", "-mfpu=neon", "-mthumb"]:
          if x in lines[i]:
            lines[i] = lines[i].replace(x, "")
            replaced = True
        if "-march=armv7-a" in lines[i]:
          lines[i] = lines[i].replace("-march=armv7-a",
                                      "-marm -mcpu=arm1176jz-s") # TODO
          replaced = True
      if replaced:
        with open(fn, "w") as f:
          for line in lines: f.write(line)

def main():
  parser = argparse.ArgumentParser()
  parser.add_argument('--ccache', action='store_true', default=False)
  parser.add_argument('--host-only', action='store_true', default=False)
  parser.add_argument('--android', action='store_true', default=False)
  parser.add_argument(
      '--export-compile-commands', action="store_true", default=False)
  parser.add_argument('--build', metavar='TARGET')
  parser.add_argument('--openbmc', action='store_true', default=False)
  parser.add_argument('--openbmc-sdk', metavar='OPENBMC_SDK')
  args = parser.parse_args()
  print(args.openbmc_sdk)

  configs = {}
  if not args.host_only:
    if args.openbmc:
      print("OpenBMC build")
    if args.android:
      for config_name, gn_args in iteritems(ANDROID_BUILD_CONFIGS):
        for arch in ANDROID_ARCHS:
          full_config_name = '%s_%s' % (config_name, arch)
          configs[full_config_name] = gn_args + ('target_cpu="%s"' % arch,)
    if args.openbmc:
      if args.openbmc_sdk is None:
        print("Please specify OpenBMC SDK location using '--openbmc-sdk SDK_PATH"
              "' when building for OpenBMC.")
        exit(0)
      openbmc_vars = GetOpenBMCVariables(args.openbmc_sdk)
      if len(openbmc_vars) < 5:
        print("The specified SDK path does not look valid.")
        exit(0)
      for config_name, gn_args in iteritems(OPENBMC_BUILD_CONFIGS):
        for arch in OPENBMC_ARCHS:
          full_config_name = '%s_%s' % (config_name, arch)
          configs[full_config_name] = gn_args + ('target_cpu="%s"' % arch,)
    else:
      for config_name, gn_args in iteritems(LINUX_BUILD_CONFIGS):
        if dict(a.split('=') for a in gn_args).get('is_clang', None) == 'true':
          continue
        for arch in LINUX_ARCHS:
          full_config_name = '%s_%s' % (config_name, arch)
          configs[full_config_name] = gn_args + ('target_cpu="%s"' % arch,
                                                 'target_os="linux"')

  system = platform.system().lower()
  if system == 'linux':
    if args.openbmc == False:
      configs.update(LINUX_BUILD_CONFIGS)
  elif system == 'darwin':
    configs.update(MAC_BUILD_CONFIGS)
  else:
    assert False, 'Unsupported system %r' % system

  if args.ccache:
    for config_name, gn_args in iteritems(configs):
      configs[config_name] = gn_args + ('cc_wrapper="ccache"',)

  out_base_dir = os.path.join(ROOT_DIR, 'out')
  if not os.path.isdir(out_base_dir):
    os.mkdir(out_base_dir)

  gn = os.path.join(ROOT_DIR, 'tools', 'gn')

  for config_name, gn_args in iteritems(configs):
    print('\n\033[32mBuilding %-20s[%s]\033[0m' % (config_name,
                                                   ','.join(gn_args)))
    out_dir = os.path.join(ROOT_DIR, 'out', config_name)
    if not os.path.isdir(out_dir):
      os.mkdir(out_dir)
    gn_cmd = (gn, 'gen', out_dir, '--args=%s' % (' '.join(gn_args)), '--check')
    if args.export_compile_commands:
      gn_cmd += ('--export-compile-commands',)
    print(' '.join(quote(c) for c in gn_cmd))
    subprocess.check_call(gn_cmd, cwd=ROOT_DIR)
    if args.build:
      ninja = os.path.join(ROOT_DIR, 'tools', 'ninja')
      ninja_cmd = (ninja, '-C', '.', args.build)
      subprocess.check_call(ninja_cmd, cwd=out_dir)

    if args.openbmc:
      print("Post-proessing OpenBMC build configuration")
      ProcessOpenBMCToolchainNinjaFile(os.path.join(out_dir, "toolchain.ninja"),
                                       openbmc_vars)
      RemoveICFAllFlag(out_dir)

if __name__ == '__main__':
  sys.exit(main())
