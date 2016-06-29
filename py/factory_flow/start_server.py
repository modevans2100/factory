# Copyright (c) 2014 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""A module for starting factory server for testing."""

import glob
import logging
import os
import re
import shutil
import stat
import subprocess
import tempfile

import factory_common   # pylint: disable=W0611
from cros.factory.factory_flow.common import (
    board_cmd_arg, bundle_dir_cmd_arg, FactoryFlowCommand, GetFactoryParPath)
from cros.factory.hacked_argparse import CmdArg
from cros.factory.hwid.v3 import hwid_utils
from cros.factory.test.env import paths
from cros.factory.umpire.common import LoadBundleManifest
from cros.factory.utils import file_utils
from cros.factory.utils import process_utils
from cros.factory.utils import sync_utils
from cros.factory.utils import sys_utils
from cros.factory.utils import type_utils


DHCPD_MESSAGE = """
*** DHCP server started with config file: %(dhcpd_conf)s.
*** DHCP server logs are stored in: %(dhcp_server_log_file)s
"""

TFTPD_MESSAGE = """
*** Netboot kernel found: %(netboot_kernel_path)s.
*** TFTP server started on %(tftpd_host_ip)s:69, serving %(tftpd_dir)s.
"""

DOWNLOAD_SERVER_MESSAGE = """
*** Download server started on port %(download_server_port)d.
*** Download server logs are stored in: %(download_server_log_file)s.
"""

SHOPFLOOR_SERVER_MESSAGE = """
*** Shopfloor server %(shopfloor_server_path)s started on
*** %(shopfloor_server_addr)s.
*** Shopfloor server logs are stored in: %(shopfloor_server_log_file)s.
"""

DHCPD_CONF_TEMPLATE = '# Generated by ' + __file__ + """
subnet %(subnet)s netmask %(netmask)s {
  next-server %(host_ip)s;
}
host dut {
  hardware ethernet %(dut_mac)s;
  fixed-address %(dut_ip)s;
}
"""


class StartServerError(Exception):
  """Start server error."""
  pass


class StartServer(FactoryFlowCommand):
  """Starts factory servers.

  This command starts the following servers required by factory flow:

  - DHCP server

    By default the command starts a DHCP server using the default DHCP daemon
    config file at /etc/dhcp/dhcpd.conf.

    To start a temporary DHCP server to serve one particular DUT, specify the
    following args: (--dhcp-iface, --host-ip, --dut-mac, --dut-ip). A temporary
    DHCP daemon config file will be generated based on the provided args; the
    temporary DHCP server will use the generated config file to serve the given
    DUT.

  - TFTP server

    The command looks for a netboot kernel at a pre-defined path:

        <bundle_dir>/factory_shim/netboot/

    If either vmlinux.bin (for depthcharge) or vmlinux.uimg (for u-boot) is
    found, the command will set up a temporary directory serving as the root
    directory of the TFTP server and start the TFTP server. The kernel binary is
    copied to the temporary root directory according to its type:

      - For depthcharge: <TFTP root dir>/vmlinux.bin
      - For u-boot: <TFTP root dir>/tftpboot/vmlinux.uimg

  - Download server

    The command starts a download server based on the mini-omaha URL set in the
    manifest file.

  - Google factory server (shop floor server)

    By default the command starts a dummy shop floor server for testing. A shop
    floor server executable can also be specified to start a custom shop floor
    server. Usually there is a start_mock_shopfloor in the bundle, which can be
    used to mimic actual shop floor communication in the factory.

  Note that with the current design of factory flow, to support multiple boards
  on the same host one needs to allocate a dedicated LAN for each board. This is
  mainly due to the hard-coded port 69 for TFTP server in netboot firmware.
  """
  # TODO(jcliang): Update this class when Umpire is ready.
  args = [
      board_cmd_arg,
      bundle_dir_cmd_arg,
      CmdArg('--stop', action='store_true',
             help='stop running servers and return'),
      CmdArg('--no-wait', dest='wait', action='store_false',
             help=('do not wait for servers; by default the command waits for '
                   'user interrupt after all servers are started, and then '
                   'stops all running servers')),
      CmdArg('--dhcp-iface',
             help='Network interface on which to run DHCP server'),
      CmdArg('--host-ip',
             help=('the IP address to assign to the DHCP network interface; '
                   'also used as the bound IP address of shop floor server')),
      CmdArg('--dut-mac',
             help='the MAC address of DUT or ethernet dongle.'),
      CmdArg('--dut-ip',
             help='the IP address to assign to DUT'),
      CmdArg('--subnet',
             help='the subnet of the testing LAN'),
      CmdArg('--netmask', default='255.255.255.0',
             help='the netmask of the testing LAN'),
      CmdArg('--shopfloor-server-exe',
             help=('the path to the executable, relative to base bundle '
                   'directory, for starting shop floor server (e.g. '
                   'shopfloor/start_mock_shopfloor); defaults to None to '
                   'start dummy shop floor server')),
      CmdArg('--fake-hwid', action='store_true',
             help=('create a fake HWID updater on shop floor server '
                   'for testing')),
      CmdArg('--no-dhcp', dest='dhcp', action='store_false',
             help='do not start DHCP server'),
      CmdArg('--no-tftp', dest='tftp', action='store_false',
             help='do not start TFTP server'),
      CmdArg('--no-download', dest='download', action='store_false',
             help='do not start download (mini-Omaha) server'),
      CmdArg('--no-shopfloor', dest='shopfloor', action='store_false',
             help='do not start shopfloor server'),
  ]

  required_packages = ('net-ftp/tftp-hpa', 'net-misc/dhcp')
  # Temporary directory to store generated files and server configs.
  files_dir = None

  dhcp_server = None
  dhcp_server_log_file = None
  dhcp_server_pid_file = None

  tftp_server = None
  tftp_server_pid_file = None

  download_server = None
  download_server_log_file = None
  download_server_pid_file = None

  shopfloor_server = None
  shopfloor_server_log_file = None
  shopfloor_server_pid_file = None

  def Init(self):
    self.files_dir = os.path.join(self.options.bundle, os.path.pardir,
                                  'start_server')
    file_utils.TryMakeDirs(self.files_dir)

    self.dhcp_server_log_file = os.path.join(
        self.files_dir, 'dhcpd.%s.log')
    self.dhcp_server_pid_file = os.path.join(
        self.files_dir, 'dhcpd.%s.pid')
    self.tftp_server_pid_file = os.path.join(
        self.files_dir, 'tftpd.pid')
    self.download_server_log_file = os.path.join(
        self.files_dir, 'download_server.log')
    self.download_server_pid_file = os.path.join(
        self.files_dir, 'download_server.pid')
    self.shopfloor_server_log_file = os.path.join(
        self.files_dir, 'shopfloor_server.log')
    self.shopfloor_server_pid_file = os.path.join(
        self.files_dir, 'shopfloor_server.pid')

  def Run(self):
    if self.options.stop:
      self.StopAllServers()
      return
    self.InstallRequiredPackages()
    self.StartDHCPServer()
    self.StartTFTPServer()
    self.StartDownloadServer()
    self.StartShopfloorServer()
    self.CreateFakeHWIDUpdater()
    if self.options.wait:
      self.WaitForUserToInterrupt()

  def StopAllServers(self):
    """Stops all existing servers."""
    logging.info('Stopping all running servers')
    servers = (
        ('DHCP server', self.dhcp_server_pid_file),
        ('TFTP server', self.tftp_server_pid_file),
        ('download server', self.download_server_pid_file),
        ('shop floor server', self.shopfloor_server_pid_file),
    )

    def KillProcess(name, pid_file):
      if os.path.exists(pid_file):
        with open(pid_file) as f:
          pid = int(f.read())
        logging.info('PID file of %s found; shut down existing %s (PID=%d)',
                     name, name, pid)
        if process_utils.SpawnOutput(['pgrep', '-F', pid_file]):
          # Send SIGINT to the process to gracefully stop it.
          process_utils.Spawn(['kill', '-SIGINT', '%d' % pid],
                              log=True, check_call=True, sudo=True)
          # Wait at most 5 seconds for process to stop.
          try:
            sync_utils.WaitFor(lambda: not process_utils.IsProcessAlive(pid), 5)
          except type_utils.TimeoutError:
            # Send SIGKILL to the process to kill it.
            process_utils.Spawn(['kill', '-SIGKILL', '%d' % pid],
                                log=True, check_call=True, sudo=True)
        else:
          logging.info(('Process with PID=%d not found; '
                        'assume it is already dead'),
                       pid)
        file_utils.TryUnlink(pid_file)

    for name, pid_file in servers:
      logging.info('Stopping %s', name)
      if name == 'DHCP server':
        pid_files = glob.glob(pid_file.replace('%s', '*'))
        for pid_file in pid_files:
          KillProcess(name, pid_file)
      else:
        KillProcess(name, pid_file)

  def InstallRequiredPackages(self):
    """Installs required packages."""
    if sys_utils.InCrOSDevice():
      # CrOS factory server has all the required packages.
      return

    for pkg in self.required_packages:
      logging.info('Checking package %s', pkg)
      is_installed = False
      try:
        process_utils.Spawn(['equery', 'list', pkg], log=True, check_call=True)
        is_installed = True
      except Exception:
        pass
      if not is_installed:
        logging.info('Package %s is not installed; trying to install it', pkg)
        # -E after sudo to propagate our custom env.
        process_utils.Spawn(
            ['sudo', '-E', 'emerge', pkg], env=dict(ACCEPT_KEYWORDS='~amd64'),
            log=True, check_call=True, log_stderr_on_error=True,
            ignore_stdout=True)

  def StartDHCPServer(self):
    """Starts DHCP server.

    Raises:
      StartServerError if DHCP server cannot be started.
    """
    if not self.options.dhcp:
      return

    logging.info('Starting DHCP server for testing')
    temp_dhcp_args = ('dhcp-iface', 'host-ip', 'dut-mac', 'dut-ip')
    temp_dhcp_args_value = [getattr(self.options, re.sub('-', '_', arg))
                            for arg in temp_dhcp_args]
    if any(temp_dhcp_args_value):
      if not all(temp_dhcp_args_value):
        raise StartServerError(
            ('Please specify all the following arguments to start a temporary '
             'DHCP server: --') +
            ', --'.join(temp_dhcp_args))
      logging.info('Configuring %s with IP %s', self.options.dhcp_iface,
                   self.options.host_ip)
      process_utils.Spawn(
          ['/bin/ifconfig', self.options.dhcp_iface, self.options.host_ip],
          check_call=True, log=True, sudo=True)

      if not self.options.subnet:
        self.options.subnet = self.options.host_ip.rsplit('.', 1)[0] + '.0'
      with tempfile.NamedTemporaryFile(
          prefix='dhcpd_', suffix='.conf', delete=False,
          dir=self.files_dir) as cfg:
        logging.info('Generating temporary DHCPD config file %s', cfg.name)
        cfg.write(DHCPD_CONF_TEMPLATE % dict(host_ip=self.options.host_ip,
                                             dut_mac=self.options.dut_mac,
                                             dut_ip=self.options.dut_ip,
                                             subnet=self.options.subnet,
                                             netmask=self.options.netmask))
        cfg.flush()
        dhcpd_conf = cfg.name
    else:
      # The default dhcpd config file.
      dhcpd_conf = '/etc/dhcp/dhcpd.conf'
    lease = tempfile.NamedTemporaryFile(
        prefix='dhcpd_', suffix='.leases', delete=False, dir=self.files_dir)
    process_utils.Spawn(['touch', lease.name], check_call=True, log=True)

    logging.info('Starting DHCP server using config %s', dhcpd_conf)
    if self.options.dut_ip:
      file_suffix = self.options.dut_ip.replace('.', '-')
    else:
      file_suffix = 'default'
    with open(self.dhcp_server_log_file % file_suffix, 'w') as f:
      self.dhcp_server = process_utils.Spawn(
          ['/usr/sbin/dhcpd', '-f', '--no-pid', '-cf', dhcpd_conf,
           '-lf', lease.name] +
          ([self.options.dhcp_iface] if self.options.dhcp_iface else []),
          stderr=subprocess.STDOUT, stdout=f, log=True, sudo=True)
    with open(self.dhcp_server_pid_file % file_suffix, 'w') as f:
      f.write(str(self.dhcp_server.pid))

    print DHCPD_MESSAGE % dict(
        dhcpd_conf=dhcpd_conf,
        dhcp_server_log_file=self.dhcp_server_log_file % file_suffix)

  def StartTFTPServer(self):
    """Starts TFTP server.

    Raises:
      StartServerError if TFTP server cannot be started.
    """
    if not self.options.tftp:
      return

    logging.info('Starting TFTP server for testing')
    tftpd_host_ip = self.options.host_ip or '0.0.0.0'
    logging.info('Checking for netboot kernel')
    if os.path.exists(os.path.join(
        self.options.bundle, 'netboot_firmware', 'image.net.bin')):
      netboot_kernel_path = os.path.join(
          self.options.bundle, 'factory_shim', 'netboot',
          'vmlinux-%s.bin' % self.options.board.full_name)
    elif os.path.exists(os.path.join(
        self.options.bundle, 'netboot_firmware',
        'nv_image-%s.bin' % self.options.board.short_name)):
      netboot_kernel_path = os.path.join(self.options.bundle, 'factory_shim',
                                         'netboot', 'vmlinux.uimg')
    else:
      logging.info('No netboot firmware found; skip netboot kernel checks')
      logging.info('TFTP server is not started')
      return

    if not os.path.exists(netboot_kernel_path):
      raise StartServerError('Expected netboot kernel %r not found' %
                             netboot_kernel_path)

    tftpd_dir = tempfile.mkdtemp(prefix='tftp_', dir=self.files_dir)
    os.chmod(tftpd_dir, stat.S_IRWXU | stat.S_IXOTH)
    if netboot_kernel_path.endswith('.bin'):
      tftpboot = tftpd_dir
    else:
      tftpboot = os.path.join(tftpd_dir, 'tftpboot')
      file_utils.TryMakeDirs(tftpboot)
      os.chmod(tftpboot, stat.S_IRWXU | stat.S_IXOTH)
    vmlinux_dest = os.path.join(tftpboot, os.path.basename(netboot_kernel_path))
    shutil.copy(netboot_kernel_path, vmlinux_dest)
    os.chmod(vmlinux_dest,
             stat.S_IWUSR | stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)

    logging.info('Starting TFTP server serving %s', tftpd_dir)
    self.tftp_server = process_utils.Spawn(
        ['/usr/sbin/in.tftpd', '-L', '--address', '%s:69' % tftpd_host_ip,
         '--secure', tftpd_dir], log=True, sudo=True)
    with open(self.tftp_server_pid_file, 'w') as f:
      f.write(str(self.tftp_server.pid))

    print TFTPD_MESSAGE % dict(
        netboot_kernel_path=netboot_kernel_path,
        tftpd_host_ip=tftpd_host_ip,
        tftpd_dir=tftpd_dir)

  def StartDownloadServer(self):
    """Starts download server."""
    if not self.options.download:
      return

    logging.info('Starting download server for testing')
    factory_setup_path = os.path.join(self.options.bundle, 'factory_setup')
    miniomaha_path = os.path.join(factory_setup_path, 'miniomaha.py')

    port = 8080
    manifest = LoadBundleManifest(
        os.path.join(self.options.bundle, 'MANIFEST.yaml'))
    mini_omaha_url = manifest.get('mini_omaha_url')
    if mini_omaha_url:
      port = int(re.match(r'http://\d+(?:.\d+){3}:(\d+)/update',
                          mini_omaha_url).group(1))

    logging.info('Validating factory configuration')
    process_utils.Spawn([miniomaha_path, '--validate_factory_config'],
                        log=True, check_call=True)

    logging.info('Starting download server on port %d', port)
    with open(self.download_server_log_file, 'w') as f:
      self.download_server = process_utils.Spawn(
          [miniomaha_path, '--port', '%d' % port],
          stderr=subprocess.STDOUT, stdout=f, log=True)
    with open(self.download_server_pid_file, 'w') as f:
      f.write(str(self.download_server.pid))

    print DOWNLOAD_SERVER_MESSAGE % dict(
        download_server_port=port,
        download_server_log_file=self.download_server_log_file)

  def StartShopfloorServer(self):
    """Starts shopfloor server."""
    if not self.options.shopfloor:
      return

    logging.info('Starting shopfloor server for testing')
    if self.options.shopfloor_server_exe:
      # If a shop floor server executable is given, then use it.
      shopfloor_server_path = os.path.join(
          self.options.bundle, self.options.shopfloor_server_exe)
      shopfloor_cmd = [shopfloor_server_path]
    else:
      # Use dummy shop floor server as default, and set shopfloor data directory
      # to the shopfloor/shopfloor_data in the bundle.
      shopfloor_server_path = os.path.join(
          self.options.bundle, 'shopfloor', 'shopfloor_server')
      shopfloor_cmd = [shopfloor_server_path, '--dummy', '--data-dir',
                       os.path.join(self.options.bundle, 'shopfloor',
                                    'shopfloor_data')]

    # Set the bound address of the shop floor server with env var.
    shopfloor_server_addr = self.options.host_ip or '0.0.0.0'
    subenv = os.environ.copy()
    subenv['CROS_SHOPFLOOR_ADDR'] = shopfloor_server_addr
    if os.path.exists(shopfloor_server_path):
      with open(self.shopfloor_server_log_file, 'w') as f:
        self.shopfloor_server = process_utils.Spawn(
            shopfloor_cmd, env=subenv, stderr=subprocess.STDOUT,
            stdout=f, log=True)
      with open(self.shopfloor_server_pid_file, 'w') as f:
        f.write(str(self.shopfloor_server.pid))

      print SHOPFLOOR_SERVER_MESSAGE % dict(
          shopfloor_server_path=' '.join(shopfloor_cmd),
          shopfloor_server_addr=shopfloor_server_addr,
          shopfloor_server_log_file=self.shopfloor_server_log_file)
    else:
      logging.warn('Cannot find shopfloor server executable')

  def CreateFakeHWIDUpdater(self):
    if not self.options.fake_hwid:
      return

    logging.info('Creating fake HWID updater for testing')
    hwid_db_name = self.options.board.short_name.upper()
    hwid_updater_filename = 'hwid_v3_bundle_%s.sh' % hwid_db_name
    shop_floor_update_dir = os.path.join(
        self.options.bundle, 'shopfloor', 'shopfloor_data', 'update')
    fake_hwid_updater_path = os.path.join(shop_floor_update_dir,
                                          hwid_updater_filename)
    # Create a temporary directory to build the fake HWID updater.
    with file_utils.TempDirectory(prefix='fake_hwid.') as temp_dir:
      # Extract the template fake HWID database and fill in the board name in
      # the database.
      factory_par_path = GetFactoryParPath()
      if factory_par_path:
        template_fake_hwid_path = os.path.join(
            'cros', 'factory', 'factory_flow', 'templates', 'FAKE_HWID')
        with file_utils.TempDirectory() as d:
          file_utils.ExtractFromPar(
              factory_par_path, template_fake_hwid_path, dest=d)
          with open(os.path.join(d, template_fake_hwid_path)) as f:
            fake_hwid_db = f.read()
      else:
        template_fake_hwid_path = os.path.join(
            paths.FACTORY_PATH, 'py', 'factory_flow', 'templates',
            'FAKE_HWID')
        with open(template_fake_hwid_path) as f:
          fake_hwid_db = f.read()
      fake_hwid_db = re.sub(r'%\{BOARD\}', hwid_db_name, fake_hwid_db)
      # Create a temp HWID database and compute the database checksum.
      temp_hwid_db_path = os.path.join(temp_dir, hwid_db_name)
      with open(temp_hwid_db_path, 'w') as f:
        f.write(fake_hwid_db)
      database_checksum = hwid_utils.ComputeDatabaseChecksum(temp_hwid_db_path)
      fake_hwid_db = re.sub(r'%\{CHECKSUM\}', database_checksum, fake_hwid_db)
      with open(temp_hwid_db_path, 'w') as f:
        f.write(fake_hwid_db)
      # Extract header from the original HWID updater.
      marker_line = r'# ----- Following data is generated by shar -----'
      with open(os.path.join(
          self.options.bundle, 'hwid', hwid_updater_filename)) as f:
        fake_hwid_updater = f.read()
      index = fake_hwid_updater.find(marker_line)
      fake_hwid_updater = fake_hwid_updater[:index + len(marker_line)]
      # Append shar output of the fake HWID database.
      shar_output = process_utils.CheckOutput(
          ['shar', '-T', '-f', temp_hwid_db_path], log=True)
      fake_hwid_updater = fake_hwid_updater + '\n' + shar_output
      # Finally create a HWID updater in shopfloor update directory.
      with open(fake_hwid_updater_path, 'w') as f:
        f.write(fake_hwid_updater)

  def WaitForUserToInterrupt(self):
    """Waits until user to interrupt the command and then stops all servers."""
    logging.info('Waiting for servers to terminate or interrupt from user')
    try:
      for process in (self.dhcp_server, self.tftp_server, self.download_server,
                      self.shopfloor_server):
        if process is not None:
          process.wait()
    finally:
      self.StopAllServers()