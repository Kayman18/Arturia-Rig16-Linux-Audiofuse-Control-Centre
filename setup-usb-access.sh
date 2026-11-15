#!/usr/bin/env bash
set -euo pipefail
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
sudo install -m 0644 "$script_dir/udev/70-arturia-af16rig.rules" /etc/udev/rules.d/70-arturia-af16rig.rules
sudo udevadm control --reload-rules
sudo udevadm trigger --action=add --subsystem-match=usb --attr-match=idVendor=1c75 --attr-match=idProduct=af21
printf '%s\n' 'AF16Rig control access rule installed. Launch the app as your normal desktop user.'
