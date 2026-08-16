# PulseArc pre-release test plan

## Automated host checks

```powershell
python -m unittest discover -s tests -v
python scripts\validate-arch-packages.py
python scripts\fetch-runtime-bundles.py
```

Godot must parse `frontend/project.godot` without errors. Every shell script in
the ArchISO overlay must pass `bash -n`.

## Virtual-machine checks

- Boot the ISO with UEFI firmware, 4 CPU threads, 8 GiB RAM, a virtual GPU,
  virtual audio, network, optical media, and a blank 24 GiB system disk.
- Confirm the native PulseArc boot animation reaches the controller menu.
- Confirm SSH reports an address in the development footer.
- Attach FAT32, exFAT, and ext4 removable images and an ISO/UDF optical image.
- Confirm one-file media launches directly and multi-file media opens Library.
- Install to the blank disk, detach the ISO, and boot the installed disk.
- Repeat with a second virtual disk size to catch fixed-size installer bugs.
- Exercise soft frontend restart, full reboot, and shutdown.
- Create a save, back it up, restore it, and verify profile isolation.
- Confirm cheats remain disabled until explicitly selected.

## Hardware checks

- Modern AMD/Intel Vulkan path.
- Ivy Bridge or comparable OpenGL-only fallback path.
- HDMI/DisplayPort audio retention across two cold boots.
- Wired Xbox-compatible controller at boot and after reconnect.
- USB, SD, CD, and DVD detection without writing to inserted media.
- Windows D3D9/11 through the selected DXVK path and WineD3D fallback.

Only a build that passes the applicable checks can be tagged or uploaded.
