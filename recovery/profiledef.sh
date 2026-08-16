#!/usr/bin/env bash

iso_name="pulsearc-recovery"
iso_label="PULSEARC_RECOVERY"
iso_publisher="PulseArc OS Project"
iso_application="PulseArc verified disk recovery"
iso_version="0.0.1"
install_dir="pulsearc"
buildmodes=('iso')
bootmodes=('bios.syslinux' 'uefi.systemd-boot')
arch="x86_64"
pacman_conf="pacman.conf"
airootfs_image_type="squashfs"
airootfs_image_tool_options=(-comp zstd -Xcompression-level 15 -b 1M)
file_permissions=(
  ["/root/.bash_profile"]="0:0:644"
  ["/root/.automated_script.sh"]="0:0:755"
  ["/usr/local/sbin/pulsearc-recover"]="0:0:755"
)
